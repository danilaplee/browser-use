import asyncio
import psutil
import logging
from database import get_db, Task
from logging_config import log_info, log_error
# Logging configuration
logger = logging.getLogger('browser-use.api')
from settings import MAX_CONCURRENT_TASKS
from telemetry import send_metrics_to_webhook, send_error_to_webhook
# Function to collect metrics periodically
async def collect_metrics_periodically():
    """Collect system metrics periodically and adjust concurrent task limit"""
    while True:
        try:
            
            # Collect metrics
            with get_db() as db:
                # Get database statistics
                total_tasks = db.query(Task).count()
                completed_tasks = db.query(Task).filter(Task.status == "completed").count()
                failed_tasks = db.query(Task).filter(Task.status == "failed").count()
                running_tasks = db.query(Task).filter(Task.status == "running").count()

                # Get system metrics
                cpu_percent = psutil.cpu_percent()
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')

                metrics = {
                    "system": {
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory.percent,
                        "disk_percent": disk.percent
                    },
                    "tasks": {
                        "total": total_tasks,
                        "completed": completed_tasks,
                        "failed": failed_tasks,
                        "running": running_tasks,
                        # "queued": task_queue.qsize(),
                        "available_slots": MAX_CONCURRENT_TASKS - running_tasks
                    }
                }

                # Log current metrics
                log_info(logger, "Updated system metrics", metrics)
                
                # Send metrics to webhook
                await send_metrics_to_webhook(metrics)
            
            # Wait 30 seconds before next collection
            await asyncio.sleep(30)
            
        except Exception as e:
            log_error(logger, f"Error collecting metrics: {str(e)}")
            await send_error_to_webhook(str(e), "collect_metrics_periodically")
            await asyncio.sleep(30)  # Wait even if error occurs

# Start periodic metrics collection
asyncio.create_task(collect_metrics_periodically())