from typing import Dict,  Any
from datetime import datetime
import asyncio
import json
import logging
from sqlalchemy.orm import Session
from database import get_db, Task, SessionLocal, get_pending_tasks
from logging_config import setup_logging, log_info, log_error
from browser import BrowserManager
# Logging configuration
logger = logging.getLogger('browser-use.queues')

browser_manager = BrowserManager()
from telemetry import send_error_to_webhook
from settings import MAX_QUEUE_SIZE, MAX_CONCURRENT_TASKS

# Task queue
task_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
running_tasks = set()
loop = asyncio.get_event_loop()

# Function to execute a task
async def execute_task(task_id: int, task: str, config: Dict[str, Any], db: Session):
    result = None
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
            config=config,
            task_id=task_id
        )

        # Update status to completed
        if db_task:
            db_task.status = "completed"
            db_task.result = json.dumps({
                "videopath":result.videopath,
                "result":result.result,
                "task":result.task,
                "steps_executed":result.steps_executed,
                "success":result.success
            })
            db_task.completed_at = datetime.utcnow()
            db.commit()

    except Exception as e:
        # Update status to failed
        if db_task:
            db_task.status = "failed"
            db_task.error = str(e)
            if result != None : 
                db_task.result = json.dumps({
                    "videopath":result.videopath,
                    "result":result.result,
                    "task":result.task,
                    "steps_executed":result.steps_executed,
                    "success":result.success
                })
            else : 
                db_task.result = json.dumps({})
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
            # Create new database session for each task
            db = SessionLocal()
            pending = get_pending_tasks(db, 0, 10)
            # log_info(logger, f"total pending: {str(len(pending))}")
            if(len(pending) == 0):
                await asyncio.sleep(10)
                loop.create_task(process_queue())
                db.close()
                return;    
            
            for task in pending:
                if task.id in running_tasks:
                    continue
                else:
                    log_info(logger, task.config)
                    await task_queue.put((task.id, task.task, json.loads(task.config)))

            if len(running_tasks) < MAX_CONCURRENT_TASKS:
                task_id, task, config = await task_queue.get()
                running_tasks.add(task_id)
                try:
                    await execute_task(task_id, task, config, db)
                except Exception as e:
                    log_error(logger, f"Error creating task: {str(e)}")
                    await send_error_to_webhook(str(e), "process_queue", task_id)
                    running_tasks.remove(task_id)
                db.close()
                
        except Exception as e:
            log_error(logger, f"Error processing queue: {str(e)}")
            await send_error_to_webhook(str(e), "process_queue")
            db.close()
        
        await asyncio.sleep(1)
        loop.create_task(process_queue())    

loop.create_task(process_queue())    

loop.run_forever()