from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
import psutil
import json
import logging
from sqlalchemy.orm import Session
from database import get_db, Task, SessionLocal
from logging_config import setup_logging, log_info, log_error
from browser import BrowserManager
from settings import TaskRequest
import aiohttp
import traceback
import os

# Logging configuration
logger = logging.getLogger('browser-use.api')

router = APIRouter(prefix="/api/v1")
browser_manager = BrowserManager()


# System settings
MAX_CONCURRENT_TASKS = 2  # Will be adjusted dynamically based on resources
MAX_QUEUE_SIZE = 10

# Task queue
task_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
running_tasks = set()

# Pydantic models
class LLMConfig(BaseModel):
    provider: str
    model_name: str
    temperature: float = 0.0

    model_config = {
        "from_attributes": True
    }

class TaskStatus(BaseModel):
    id: int
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True
    }

class SystemMetrics(BaseModel):
    cpu_usage: float
    memory_usage: float
    active_tasks: int
    queued_tasks: int
    max_concurrent_tasks: int
    available_slots: int

# Webhook URLs
ERROR_WEBHOOK_URL = os.getenv("ERROR_WEBHOOK_URL","https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/browser-use-vra-handler")
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL","https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/notify-run")
METRICS_WEBHOOK_URL = os.getenv("METRICS_WEBHOOK_URL","https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/status")

async def send_error_to_webhook(error: str, context: str, task_id: Optional[int] = None):
    """Send error information to webhook"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "error": error,
                "context": context,
                "task_id": task_id,
                "timestamp": datetime.utcnow().isoformat(),
                "stack_trace": traceback.format_exc()
            }
            async with session.post(ERROR_WEBHOOK_URL, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to send error to webhook: {response.status}")
    except Exception as e:
        logger.error(f"Error sending to webhook: {str(e)}")

async def notify_new_run(task_id: int, task: str, config: Dict[str, Any]):
    """Notify webhook about a new task"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "task_id": task_id,
                "task": task,
                "config": config,
                "timestamp": datetime.utcnow().isoformat()
            }
            async with session.post(NOTIFY_WEBHOOK_URL, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to notify about new task: {response.status}")
    except Exception as e:
        logger.error(f"Error notifying about new task: {str(e)}")

async def send_metrics_to_webhook(metrics: Dict[str, Any]):
    """Send system metrics to webhook"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "metrics": metrics,
                "timestamp": datetime.utcnow().isoformat()
            }
            async with session.post(METRICS_WEBHOOK_URL, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to send metrics to webhook: {response.status}")
    except Exception as e:
        logger.error(f"Error sending metrics to webhook: {str(e)}")

# Function to calculate available resources
def calculate_max_tasks():
    cpu_count = psutil.cpu_count()
    memory = psutil.virtual_memory()
    
    # Considering each task uses ~0.5 CPU and 400MB RAM
    max_by_cpu = int(cpu_count * 2)  # 2 tasks per CPU
    max_by_memory = int(memory.available / (400 * 1024 * 1024))  # 400MB per task
    
    # Maximum limit based on resources
    max_tasks = min(max_by_cpu, max_by_memory)
    
    # Absolute maximum limit of 32 tasks
    return min(max_tasks, 32)

# Function to execute a task
async def execute_task(task_id: int, task: str, config: Dict[str, Any], db: Session):
    try:
        # Update status to running
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if db_task:
            db_task.status = "running"
            db_task.started_at = datetime.utcnow()
            db.commit()

        # Execute task
        result = await browser_manager.execute_task(
            task=task,
            config=config
        )

        # Update status to completed
        if db_task:
            db_task.status = "completed"
            db_task.result = json.dumps({
                "videopath":result.videopath
            })
            db_task.completed_at = datetime.utcnow()
            db.commit()

    except Exception as e:
        # Update status to failed
        if db_task:
            db_task.status = "failed"
            db_task.error = str(e)
            db_task.result = json.dumps({
                "videopath":result.videopath
            })
            db_task.completed_at = datetime.utcnow()
            db.commit()
        await send_error_to_webhook(str(e), "execute_task", task_id)
        raise
    finally:
        running_tasks.remove(task_id)
        try:
            db.close()
        except:
            pass

# Function to process the queue
async def process_queue():
    while True:
        try:
            if len(running_tasks) < MAX_CONCURRENT_TASKS:
                task_id, task, config = await task_queue.get()
                running_tasks.add(task_id)
                
                # Create new database session for each task
                db = SessionLocal()
                try:
                    asyncio.create_task(execute_task(task_id, task, config, db))
                except Exception as e:
                    log_error(logger, f"Error creating task: {str(e)}")
                    await send_error_to_webhook(str(e), "process_queue", task_id)
                    running_tasks.remove(task_id)
                    db.close()
                
            await asyncio.sleep(1)
        except Exception as e:
            log_error(logger, f"Error processing queue: {str(e)}")
            await send_error_to_webhook(str(e), "process_queue")
            await asyncio.sleep(1)

# Start queue processing
asyncio.create_task(process_queue())

# Function to collect metrics periodically
async def collect_metrics_periodically():
    """Collect system metrics periodically and adjust concurrent task limit"""
    while True:
        try:
            # Update concurrent task limit based on resources
            global MAX_CONCURRENT_TASKS
            MAX_CONCURRENT_TASKS = calculate_max_tasks()
            
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
                        "queued": task_queue.qsize(),
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

@router.post("/run")
async def run_task(request: TaskRequest):
    """Execute a new automation task"""
    try:

        # Create new task in database
        with get_db() as db:
            db_task = Task(
                task=request.task,
                config=json.dumps({
                    "llm_config": request.llm_config.model_dump(),
                    "browser_config": request.browser_config.model_dump() if request.browser_config else {},
                    "max_steps": request.max_steps,
                    "use_vision": request.use_vision
                }),
                status="pending",
                created_at=datetime.utcnow()
            )
            db.add(db_task)
            db.commit()
            db.refresh(db_task)

            # Notify about new task
            await notify_new_run(
                task_id=db_task.id,
                task=request.task,
                config=request.model_dump()
            )

            # Add to queue
            await task_queue.put((db_task.id, request.task, request.model_dump()))

            return {"task_id": db_task.id}

    except Exception as e:
        log_error(logger, f"Error executing task: {str(e)}")
        await send_error_to_webhook(str(e), "run_task")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/task/{task_id}/status")
async def get_task_status(task_id: int):
    """Return task status"""
    try:
        with get_db() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")

            return {
                "task_id": task.id,
                "status": task.status,
                "result": task.result if task.status == "completed" else None,
                "error": task.error if task.status == "failed" else None
            }

    except Exception as e:
        log_error(logger, f"Error getting task status: {str(e)}")
        await send_error_to_webhook(str(e), "get_task_status", task_id)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/metrics")
async def get_metrics():
    """Return system metrics"""
    try:
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
                    "queued": task_queue.qsize(),
                    "available_slots": MAX_CONCURRENT_TASKS - running_tasks
                }
            }

            # Send metrics to webhook
            await send_metrics_to_webhook(metrics)

            return metrics

    except Exception as e:
        log_error(logger, f"Error getting metrics: {str(e)}")
        await send_error_to_webhook(str(e), "get_metrics")
        raise HTTPException(status_code=500, detail=str(e))