from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json
import time
import psutil
from datetime import datetime, timedelta
import asyncio
from queue import PriorityQueue
import threading
import logging
import uvicorn
from logging_config import setup_logging, log_info, log_error

from config import settings
from database import get_db
from models import Task, Base
from browser import BrowserManager
from schemas import TaskCreate, TaskResponse, TaskUpdate,  BrowserSessionResponse
from crud import (
    create_task, get_tasks, get_task, update_task, delete_task,
    get_browser_sessions, get_browser_session,
    get_browser_sessions_by_task
)
from notifications import webhook_manager
from api import router as api_router
from metrics import collect_metrics_periodically

# Logging configuration
logger = logging.getLogger('browser-use.main')

app = FastAPI(
    title="Browser Automation API",
    description="API for browser automation with session management",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router)

# Database initialization
Base.metadata.create_all(bind=settings.engine)

# Global BrowserManager instance
browser_manager = BrowserManager()

# Priority queue for tasks
task_queue = PriorityQueue()
task_lock = threading.Lock()

# Running tasks
active_tasks = {}

async def process_task_queue():
    """Processes the task queue in priority order"""
    while True:
        try:
            with task_lock:
                if not task_queue.empty():
                    priority, task_id = task_queue.get()
                    task = await get_task_from_db(task_id)
                    
                    if task and task.status == "pending":
                        await execute_task(task)
                        
        except Exception as e:
            log_error(logger, "Error processing task queue", {
                "error": str(e)
            }, exc_info=True)
            
        await asyncio.sleep(1)

async def get_task_from_db(task_id: int) -> Optional[Task]:
    """Gets a task from the database"""
    async with get_db() as db:
        return await db.query(Task).filter(Task.id == task_id).first()

async def execute_task(task: Task):
    """Executes a task"""
    try:
        # Update status to running
        async with get_db() as db:
            task.status = "running"
            task.started_at = datetime.utcnow()
            await db.commit()
        
        # Notify execution start
        await webhook_manager.notify_run(
            task_id=task.id,
            task_data={
                "task": task.task,
                "config": task.config,
                "priority": task.priority
            }
        )
        
        # Execute task with timeout
        try:
            result = await asyncio.wait_for(
                browser_manager.execute_task(task.task, task.config or {}),
                timeout=task.timeout
            )
            
            # Update result
            async with get_db() as db:
                task.status = "completed"
                task.result = json.dumps(result)
                task.completed_at = datetime.utcnow()
                await db.commit()
                
        except asyncio.TimeoutError:
            error_msg = "Task timeout"
            async with get_db() as db:
                task.status = "failed"
                task.error = error_msg
                task.completed_at = datetime.utcnow()
                await db.commit()
            
            # Notify error
            await webhook_manager.notify_error(
                task_id=task.id,
                error=error_msg,
                task_data={
                    "task": task.task,
                    "config": task.config,
                    "priority": task.priority
                }
            )
            
    except Exception as e:
        log_error(logger, "Error executing task", {
            "task_id": task.id,
            "error": str(e)
        }, exc_info=True)
        async with get_db() as db:
            task.status = "failed"
            task.error = str(e)
            task.completed_at = datetime.utcnow()
            await db.commit()
            
        # Notify error
        await webhook_manager.notify_error(
            task_id=task.id,
            error=str(e),
            task_data={
                "task": task.task,
                "config": task.config,
                "priority": task.priority
            }
        )

async def collect_metrics():
    """Collects and sends metrics periodically"""
    while True:
        try:
            # Collect system metrics
            metrics = {
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent,
                "active_tasks": len(active_tasks),
                "browser_metrics": browser_manager.get_metrics()
            }
            
            # Send metrics via webhook
            await webhook_manager.send_status(metrics)
            
        except Exception as e:
            log_error(logger, "Error collecting metrics", {
                "error": str(e)
            }, exc_info=True)
            
        await asyncio.sleep(3600)  # Collect every hour

@app.on_event("startup")
async def startup_event():
    """Initializes the browser manager on application startup"""
    try:
        await browser_manager.initialize()
        log_info(logger, "BrowserManager initialized successfully")
    except Exception as e:
        log_error(logger, "Error initializing BrowserManager", {
            "error": str(e)
        }, exc_info=True)
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Closes the browser manager on application shutdown"""
    try:
        await browser_manager.close()
        log_info(logger, "BrowserManager closed successfully")
    except Exception as e:
        log_error(logger, "Error closing BrowserManager", {
            "error": str(e)
        }, exc_info=True)

@app.post("/run")
async def run_task(task: TaskCreate, db: Session = Depends(get_db)):
    """Executes a new automation task"""
    try:
        # Create task in database
        db_task = await create_task(db, task)
        log_info(logger, "Task created successfully", {
            "task_id": db_task.id
        })
        
        # Execute task using session pool
        result = await browser_manager.execute_task(task.task, task.config)
        log_info(logger, "Task executed successfully", {
            "task_id": db_task.id
        })
        
        # Update task status and result
        db_task.status = "completed"
        db_task.result = str(result)
        db_task.completed_at = datetime.utcnow()
        await db.commit()
        
        return TaskResponse(
            id=db_task.id,
            status=db_task.status,
            priority=db_task.priority,
            result=db_task.result,
            error=db_task.error,
            created_at=db_task.created_at,
            completed_at=db_task.completed_at
        )
    except Exception as e:
        log_error(logger, "Error executing task", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_metrics():
    """Returns system and browser metrics"""
    try:
        return await browser_manager.get_metrics()
    except Exception as e:
        log_error(logger, "Error getting metrics", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Lists all tasks with pagination"""
    try:
        tasks = await get_tasks(db, skip=skip, limit=limit)
        return [
            TaskResponse(
                id=task.id,
                status=task.status,
                priority=task.priority,
                result=task.result,
                error=task.error,
                created_at=task.created_at,
                completed_at=task.completed_at
            )
            for task in tasks
        ]
    except Exception as e:
        log_error(logger, "Error listing tasks", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_by_id(task_id: int, db: Session = Depends(get_db)):
    """Gets details of a specific task"""
    try:
        task = await get_task(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return TaskResponse(
            id=task.id,
            status=task.status,
            priority=task.priority,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            completed_at=task.completed_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Error getting task", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks", response_model=TaskResponse)
async def create_new_task(task: TaskCreate, db: Session = Depends(get_db)):
    """Creates a new task"""
    try:
        db_task = await create_task(db, task)
        log_info(logger, "Task created successfully", {
            "task_id": db_task.id
        })
        return TaskResponse(
            id=db_task.id,
            status=db_task.status,
            priority=db_task.priority,
            result=db_task.result,
            error=db_task.error,
            created_at=db_task.created_at,
            completed_at=db_task.completed_at
        )
    except Exception as e:
        log_error(logger, "Error creating task", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_existing_task(task_id: int, task: TaskUpdate, db: Session = Depends(get_db)):
    """Updates an existing task"""
    try:
        db_task = await update_task(db, task_id, task)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        log_info(logger, "Task updated successfully", {
            "task_id": task_id
        })
        return TaskResponse(
            id=db_task.id,
            status=db_task.status,
            priority=db_task.priority,
            result=db_task.result,
            error=db_task.error,
            created_at=db_task.created_at,
            completed_at=db_task.completed_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Error updating task", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
async def delete_existing_task(task_id: int, db: Session = Depends(get_db)):
    """Deletes a task"""
    try:
        success = await delete_task(db, task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        log_info(logger, "Task deleted successfully", {
            "task_id": task_id
        })
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Error deleting task", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser-sessions", response_model=List[BrowserSessionResponse])
async def list_browser_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Lists all browser sessions with pagination"""
    try:
        sessions = await get_browser_sessions(db, skip=skip, limit=limit)
        return [
            BrowserSessionResponse(
                id=session.id,
                task_id=session.task_id,
                status=session.status,
                config=session.config,
                metadata=session.metadata,
                created_at=session.created_at,
                updated_at=session.updated_at
            )
            for session in sessions
        ]
    except Exception as e:
        log_error(logger, "Error listing sessions", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser-sessions/{session_id}", response_model=BrowserSessionResponse)
async def get_browser_session_by_id(session_id: int, db: Session = Depends(get_db)):
    """Gets details of a specific session"""
    try:
        session = await get_browser_session(db, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Browser session not found")
        return BrowserSessionResponse(
            id=session.id,
            task_id=session.task_id,
            status=session.status,
            config=session.config,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=session.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Error getting session", {
            "session_id": session_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}/browser-sessions", response_model=List[BrowserSessionResponse])
async def get_task_browser_sessions(task_id: int, db: Session = Depends(get_db)):
    """Lists all sessions associated with a task"""
    try:
        sessions = await get_browser_sessions_by_task(db, task_id)
        return [
            BrowserSessionResponse(
                id=session.id,
                task_id=session.task_id,
                status=session.status,
                config=session.config,
                metadata=session.metadata,
                created_at=session.created_at,
                updated_at=session.updated_at
            )
            for session in sessions
        ]
    except Exception as e:
        log_error(logger, "Error getting task sessions", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    log_error(logger, "Unhandled error", {
        "error": str(exc)
    }, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

@app.get("/health")
async def health_check():
    """Application health check endpoint"""
    return {"status": "healthy"}

@app.get("/tasks/", response_model=List[TaskResponse])
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    tasks = await get_tasks(db, skip=skip, limit=limit)
    return [
        TaskResponse(
            id=task.id,
            status=task.status,
            priority=task.priority,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            completed_at=task.completed_at
        )
        for task in tasks
    ]

@app.get("/metrics/errors")
async def get_error_metrics(db: Session = Depends(get_db)):
    """Returns error metrics"""
    try:
        last_hour = datetime.utcnow() - timedelta(hours=1)
        error_tasks = db.query(Task).filter(
            Task.status == "failed",
            Task.created_at >= last_hour
        ).all()
        
        return {
            "total_errors": len(error_tasks),
            "errors": [
                {
                    "task_id": task.id,
                    "error": task.error,
                    "timestamp": task.created_at.isoformat()
                } for task in error_tasks
            ]
        }
    except Exception as e:
        log_error(logger, "Error getting error metrics", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def main():
    """Main function that starts the server and metrics collector"""
    try:
        log_info(logger, "Starting application")
        
        # Start metrics collector in background
        log_info(logger, "Starting metrics collector")
        asyncio.create_task(collect_metrics_periodically())
        
        # Start FastAPI server
        log_info(logger, "Starting FastAPI server")
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
        
    except Exception as e:
        log_error(logger, "Error starting application", {
            "error": str(e)
        }, exc_info=True)
        raise

if __name__ == "__main__":
    # Configure logging
    setup_logging()
    
    # Run the application
    asyncio.run(main())