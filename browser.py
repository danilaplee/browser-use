import logging
from typing import Dict, Any
from datetime import datetime
import time
from collections import defaultdict
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning
from settings import get_llm, AgentResponse, ModelConfig
from browser_use import Agent, BrowserConfig, Browser
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


class BrowserManager:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        log_info(logger, "BrowserManager initialized")
        self.metrics_collector = MetricsCollector()

    async def execute_task(self, task: str, config: Dict[str, Any]) -> AgentResponse:
        """Execute an automation task"""
        
        try:
            # Configure LLM model
            llm_config = ModelConfig(
                provider=config.get("llm_config", {}).get("provider", "OpenAI"),
                model_name=config.get("llm_config", {}).get("model_name", "chat"),
                api_key=config.get("llm_config", {}).get("api_key", None),
                temperature=config.get("llm_config", {}).get("temperature", 0.5)
            )
            llm = get_llm(llm_config)
            
            # Configure browser
            browser_config = BrowserConfig(
                headless=config.get("browser_config", {}).get("headless", True),
                disable_security=config.get("browser_config", {}).get("disable_security", True),
                extra_chromium_args=config.get("browser_config", {}).get("extra_chromium_args", [])
            )
            # Initialize browser
            browser = Browser(config=browser_config)
            
            tool_calling_method = "auto"
            if "deepseek-r1" in llm_config.model_name:
                tool_calling_method = "json_mode"
            # Initialize and run agent
            agent = Agent(
                task=task, 
                llm=llm, 
                browser=browser,
                max_failures=config.get("max_failures", 5),
                use_vision=config.get("use_vision", True),
                memory_interval=config.get("memory_interval", 10),
                planner_interval=config.get("planner_interval", 1),
                tool_calling_method=tool_calling_method
            )
            
            result = await agent.run(max_steps=config.get("max_steps", 5))
            
            # Extract result
            success = False
            content = "Task not completed"
            videopath = agent.videopath
            if result and result.history and len(result.history) > 0:
                last_item = result.history[-1]
                if last_item.result and len(last_item.result) > 0:
                    last_result = last_item.result[-1]
                    content = last_result.extracted_content or "No content extracted"
                    success = last_result.is_done
            
            # Close browser after use
            await browser.close()
            
            return AgentResponse(
                task=task,
                result=content,
                success=success,
                steps_executed=len(result.history) if result and result.history else 0,
                videopath=videopath
            )

        except Exception as e:
            logger.error(f"Error executing task: {str(e)}")
            self.metrics_collector.record_metric("task_errors", 1)
            return AgentResponse(task=task, result=None, success=False, error=str(e))

    def get_metrics(self) -> Dict[str, Any]:
        """Return browser manager metrics"""
        metrics = self.metrics_collector.get_metrics()
        return metrics