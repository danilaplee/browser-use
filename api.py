from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional, Any
from datetime import datetime
import psutil
import json
import logging
from database import get_db, Task
from logging_config import log_error
from settings import TaskRequest, MAX_CONCURRENT_TASKS

# Logging configuration
logger = logging.getLogger('browser-use.api')

router = APIRouter(prefix="/api/v1")
from telemetry import send_metrics_to_webhook, send_error_to_webhook, notify_new_run


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
                    "use_vision": request.use_vision,
                    "history": request.history,
                    "run_history": request.run_history,
                    "max_retries":request.max_retries,
                    "delay_between_actions":request.delay_between_actions,
                    "skip_failures":request.skip_failures,
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

            return {"task_id": db_task.id}

    except Exception as e:
        log_error(logger, f"Error executing task: {str(e)}")
        await send_error_to_webhook(str(e), "run_task")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/task/{task_id}/status")
async def get_task_status(task_id: str):
    """Return task status"""
    try:
        with get_db() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")

            return {
                "task_id": task.id,
                "status": task.status,
                "result": json.loads(task.result) if task.status == "completed" else None,
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
                    # "queued": task_queue.qsize(),
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