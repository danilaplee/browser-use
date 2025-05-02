import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from config import settings
import functools
import time
from collections import defaultdict
import json
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning

# Logging configuration
logger = logging.getLogger('browser-use.browser')

class MetricsCollector:
    def __init__(self):
        self.metrics = defaultdict(list)
        self.start_time = time.time()
        
    def record_metric(self, name: str, value: float):
        self.metrics[name].append({
            "value": value,
            "timestamp": datetime.now().isoformat()
        })
        
    def get_metrics(self) -> Dict[str, Any]:
        return {
            "uptime": time.time() - self.start_time,
            "metrics": dict(self.metrics)
        }

class BrowserSession:
    def __init__(self, browser: Browser, context: BrowserContext, page: Page):
        self.browser = browser
        self.context = context
        self.page = page
        self.last_used = datetime.now()
        self.is_busy = False
        self.metrics = {
            "requests": 0,
            "errors": 0,
            "total_time": 0
        }

    async def close(self):
        """Close the browser session"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

class SessionPool:
    def __init__(self, max_sessions: int = 5, session_timeout: int = 300):
        self.sessions: list[BrowserSession] = []
        self.max_sessions = max_sessions
        self.session_timeout = session_timeout
        self.playwright = None
        self._lock = asyncio.Lock()
        self.metrics_collector = MetricsCollector()
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes

    def _cache_key(self, task: str, config: Dict[str, Any]) -> str:
        return f"{task}:{json.dumps(config, sort_keys=True)}"

    async def initialize(self):
        """Initialize Playwright if needed"""
        if not self.playwright:
            self.playwright = await async_playwright().start()

    async def get_session(self) -> BrowserSession:
        """Get an available session or create a new one"""
        async with self._lock:
            start_time = time.time()
            
            # Clean up inactive sessions
            await self._cleanup_inactive_sessions()

            # Try to find an available session
            for session in self.sessions:
                if not session.is_busy:
                    session.is_busy = True
                    session.last_used = datetime.now()
                    self.metrics_collector.record_metric("session_wait_time", time.time() - start_time)
                    return session

            # If none found and can create new session
            if len(self.sessions) < self.max_sessions:
                session = await self._create_new_session()
                self.metrics_collector.record_metric("session_wait_time", time.time() - start_time)
                return session

            # Wait for a session to become available
            while True:
                for session in self.sessions:
                    if not session.is_busy:
                        session.is_busy = True
                        session.last_used = datetime.now()
                        self.metrics_collector.record_metric("session_wait_time", time.time() - start_time)
                        return session
                await asyncio.sleep(0.1)

    async def release_session(self, session: BrowserSession):
        """Release a session for reuse"""
        async with self._lock:
            session.is_busy = False
            session.last_used = datetime.now()

    async def _create_new_session(self) -> BrowserSession:
        """Create a new browser session"""
        start_time = time.time()
        
        if not self.playwright:
            await self.initialize()

        browser = await self.playwright.chromium.launch(
            headless=settings.BROWSER_USE_HEADLESS,
            args=['--no-sandbox']
        )
        context = await browser.new_context()
        page = await context.new_page()
        
        session = BrowserSession(browser, context, page)
        session.is_busy = True
        self.sessions.append(session)
        
        self.metrics_collector.record_metric("session_creation_time", time.time() - start_time)
        return session

    async def _cleanup_inactive_sessions(self):
        """Remove inactive sessions that exceeded timeout"""
        now = datetime.now()
        sessions_to_remove = []
        
        for session in self.sessions:
            if not session.is_busy and (now - session.last_used).total_seconds() > self.session_timeout:
                sessions_to_remove.append(session)
        
        for session in sessions_to_remove:
            await session.close()
            self.sessions.remove(session)
            
        self.metrics_collector.record_metric("active_sessions", len(self.sessions))

    def get_metrics(self) -> Dict[str, Any]:
        """Return session pool metrics"""
        metrics = self.metrics_collector.get_metrics()
        metrics.update({
            "active_sessions": len(self.sessions),
            "busy_sessions": sum(1 for s in self.sessions if s.is_busy),
            "cache_size": len(self._cache)
        })
        return metrics

class BrowserManager:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        log_info(logger, "BrowserManager initialized")
        self.session_pool = SessionPool()
        self.metrics_collector = MetricsCollector()

    async def start(self):
        """Start the browser and configure context"""
        try:
            log_info(logger, "Starting browser")
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context(record_video_dir="videos/")
            self.page = await self.context.new_page()
            log_info(logger, "Browser started successfully")
        except Exception as e:
            log_error(logger, "Error starting browser", {
                "error": str(e)
            }, exc_info=True)
            raise

    async def navigate(self, url: str):
        """Navigate to a specific URL"""
        try:
            log_info(logger, "Navigating to URL", {
                "url": url
            })
            await self.page.goto(url)
            log_debug(logger, "Navigation completed", {
                "url": url
            })
        except Exception as e:
            log_error(logger, "Error navigating to URL", {
                "url": url,
                "error": str(e)
            }, exc_info=True)
            raise

    async def close(self):
        """Close the browser and clean up resources"""
        try:
            log_info(logger, "Closing browser")
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            log_info(logger, "Browser closed successfully")
        except Exception as e:
            log_error(logger, "Error closing browser", {
                "error": str(e)
            }, exc_info=True)
            raise

    async def get_page_content(self) -> str:
        """Get current page content"""
        try:
            log_debug(logger, "Getting page content")
            content = await self.page.content()
            log_debug(logger, "Content retrieved successfully")
            return content
        except Exception as e:
            log_error(logger, "Error getting page content", {
                "error": str(e)
            }, exc_info=True)
            raise

    async def execute_script(self, script: str):
        """Execute a JavaScript script on the page"""
        try:
            log_debug(logger, "Executing script", {
                "script": script
            })
            result = await self.page.evaluate(script)
            log_debug(logger, "Script executed successfully")
            return result
        except Exception as e:
            log_error(logger, "Error executing script", {
                "script": script,
                "error": str(e)
            }, exc_info=True)
            raise

    async def execute_task(self, task: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an automation task"""
        session = None
        start_time = time.time()
        
        try:
            # Check cache
            cache_key = self.session_pool._cache_key(task, config)
            if cache_key in self.session_pool._cache:
                cached_result = self.session_pool._cache[cache_key]
                if time.time() - cached_result["timestamp"] < self.session_pool._cache_ttl:
                    self.metrics_collector.record_metric("cache_hits", 1)
                    return cached_result["result"]

            # Get a session from the pool
            session = await self.session_pool.get_session()

            # Default settings
            default_config = {
                "timeout": 30000,
                "wait_until": "networkidle",
                "viewport": {"width": 1280, "height": 720}
            }
            config = {**default_config, **config}

            # Execute the task
            result = await self._execute_task_internal(session, task, config)
            await session.close()
            # Update cache
            self.session_pool._cache[cache_key] = {
                "result": result,
                "timestamp": time.time()
            }
            
            self.metrics_collector.record_metric("task_execution_time", time.time() - start_time)
            return {"success": True, "result": result}

        except Exception as e:
            logger.error(f"Error executing task: {str(e)}")
            self.metrics_collector.record_metric("task_errors", 1)
            return {"success": False, "error": str(e)}

        finally:
            if session:
                await self.session_pool.release_session(session)

    async def _execute_task_internal(self, session: BrowserSession, task: str, config: Dict[str, Any]) -> Any:
        """Execute internal task logic"""
        if task.startswith("navigate:"):
            url = task.split(":", 1)[1]
            await session.page.goto(url, timeout=config["timeout"], wait_until=config["wait_until"])
            return {"url": url, "title": await session.page.title()}
        
        elif task.startswith("screenshot:"):
            url = task.split(":", 1)[1]
            await session.page.goto(url, timeout=config["timeout"], wait_until=config["wait_until"])
            screenshot = await session.page.screenshot()
            return {"screenshot": screenshot}
        
        else:
            raise ValueError(f"Unsupported task type: {task}")

    def get_metrics(self) -> Dict[str, Any]:
        """Return browser manager metrics"""
        metrics = self.metrics_collector.get_metrics()
        metrics.update(self.session_pool.get_metrics())
        return metrics