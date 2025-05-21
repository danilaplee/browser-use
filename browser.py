import logging
from typing import Dict, Any
from datetime import datetime
import time
import json
from collections import defaultdict
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning
from settings import get_llm, AgentResponse, ModelConfig
from browser_use import Agent, BrowserConfig, Browser, AgentHistoryList
# from browser_use.agent.views import AgentHistory
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

    async def execute_task(self, task: str, config: Dict[str, Any], task_id: str) -> AgentResponse:
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
            bconfig = config.get("browser_config", {})
            history = config.get("history", None)
            run_history = config.get("run_history", False)
            # Configure browser
            browser_config = BrowserConfig(
                headless=bconfig.get("headless", True),
                disable_security=bconfig.get("disable_security", True),
                extra_chromium_args=bconfig.get("extra_chromium_args", []),
                proxy=bconfig.get("proxy", None)
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
            
            history_path = f'./history/{task_id}.json'
            # Extract result
            success = False
            content = "Task not completed"
            steps_executed = 0

            async def onStepEnd(self: Agent): 
                self.save_history(history_path)

            if run_history:
                log_info(logger, f"TASK {task_id} run history {str(history)}")
                with open(history_path, "w") as f:
                    json.dump(history, f)
                result = await agent.rerun_history(
                    history=AgentHistoryList.load_from_file(history_path, agent.AgentOutput), 
                    max_retries=config.get("max_retries", 3),
                    skip_failures=config.get("skip_failures", False),
                    delay_between_actions=config.get("delay_between_actions", 2.0)
                )
                last_item = result[-1]
                success = last_item.success
                steps_executed = len(result)
                content = last_item.extracted_content
                # await (await browser.get_playwright_browser()).close()
                
            else:
                log_info(logger, f"TASK {task_id} run ai")
                result = await agent.run(max_steps=config.get("max_steps", 5), 
                                     on_step_start=None,
                                     on_step_end=onStepEnd)
                if result and result.history and len(result.history) > 0:
                    steps_executed = len(result.history)
                    last_item = result.history[-1]
                    if last_item.result and len(last_item.result) > 0:
                        last_result = last_item.result[-1]
                        content = last_result.extracted_content or "No content extracted"
                        success = last_result.is_done
                # Close browser after use
                await browser.close()
            videopath = agent.videopath
            
            return AgentResponse(
                task=task,
                result=content,
                success=success,
                steps_executed=steps_executed,
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