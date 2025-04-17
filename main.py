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

from config import settings
from database import get_db
from models import Task, Metric, Base, BrowserSession
from browser import BrowserManager
from schemas import TaskCreate, TaskResponse, TaskUpdate, BrowserSessionCreate, BrowserSessionResponse
from crud import (
    create_task, get_tasks, get_task, update_task, delete_task,
    create_browser_session, get_browser_sessions, get_browser_session,
    get_browser_sessions_by_task
)
from notifications import webhook_manager

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Browser-use API",
    description="API para automação de navegador",
    version="1.0.0"
)

# Configuração CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicialização do banco de dados
Base.metadata.create_all(bind=settings.engine)

# Instância global do BrowserManager
browser_manager = BrowserManager()

# Fila de prioridade para tarefas
task_queue = PriorityQueue()
task_lock = threading.Lock()

# Tarefas em execução
active_tasks = {}

async def process_task_queue():
    """Processa a fila de tarefas em ordem de prioridade"""
    while True:
        try:
            with task_lock:
                if not task_queue.empty():
                    priority, task_id = task_queue.get()
                    task = await get_task_from_db(task_id)
                    
                    if task and task.status == "pending":
                        await execute_task(task)
                        
        except Exception as e:
            logger.error(f"Erro ao processar fila de tarefas: {str(e)}")
            
        await asyncio.sleep(1)

async def get_task_from_db(task_id: int) -> Optional[Task]:
    """Obtém uma tarefa do banco de dados"""
    async with get_db() as db:
        return await db.query(Task).filter(Task.id == task_id).first()

async def execute_task(task: Task):
    """Executa uma tarefa"""
    try:
        # Atualiza status para running
        async with get_db() as db:
            task.status = "running"
            task.started_at = datetime.utcnow()
            await db.commit()
        
        # Notifica início da execução
        await webhook_manager.notify_run(
            task_id=task.id,
            task_data={
                "task": task.task,
                "config": task.config,
                "priority": task.priority
            }
        )
        
        # Executa a tarefa com timeout
        try:
            result = await asyncio.wait_for(
                browser_manager.execute_task(task.task, task.config or {}),
                timeout=task.timeout
            )
            
            # Atualiza resultado
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
            
            # Notifica erro
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
        logger.error(f"Erro ao executar tarefa {task.id}: {str(e)}")
        async with get_db() as db:
            task.status = "failed"
            task.error = str(e)
            task.completed_at = datetime.utcnow()
            await db.commit()
            
        # Notifica erro
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
    """Coleta e envia métricas periodicamente"""
    while True:
        try:
            # Coleta métricas do sistema
            metrics = {
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent,
                "active_tasks": len(active_tasks),
                "browser_metrics": browser_manager.get_metrics()
            }
            
            # Envia métricas via webhook
            await webhook_manager.send_status(metrics)
            
        except Exception as e:
            logger.error(f"Erro ao coletar métricas: {str(e)}")
            
        await asyncio.sleep(3600)  # Coleta a cada hora

@app.on_event("startup")
async def startup():
    # Inicia o processador de tarefas
    asyncio.create_task(process_task_queue())
    # Inicia o coletor de métricas
    asyncio.create_task(collect_metrics())
    await browser_manager.initialize()

@app.on_event("shutdown")
async def shutdown():
    await browser_manager.close()
    await webhook_manager.close()

@app.post("/run", response_model=TaskResponse)
async def run_task(task: TaskCreate, request: Request):
    """Cria e agenda uma nova tarefa"""
    try:
        # Cria nova tarefa no banco de dados
        async with get_db() as db:
            db_task = Task(
                task=task.task,
                config=task.config,
                status="pending",
                priority=task.priority,
                max_retries=task.max_retries,
                timeout=task.timeout,
                tags=task.tags,
                metadata=task.metadata
            )
            db.add(db_task)
            await db.commit()
            await db.refresh(db_task)
            
            # Adiciona à fila de prioridade
            with task_lock:
                task_queue.put((-db_task.priority, db_task.id))
            
            # Executa a tarefa usando o pool de sessões
            result = await browser_manager.execute_task(task.task, task.config)
            
            # Atualiza o status e resultado da tarefa
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
        logger.error(f"Erro ao criar tarefa: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/task/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int):
    """Obtém o status e resultado de uma tarefa"""
    try:
        task = await get_task_from_db(task_id)
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
        
    except Exception as e:
        logger.error(f"Erro ao obter tarefa {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/queue")
async def get_task_queue():
    """Retorna o estado atual da fila de tarefas"""
    with task_lock:
        queue_items = []
        temp_queue = PriorityQueue()
        
        while not task_queue.empty():
            priority, task_id = task_queue.get()
            queue_items.append({
                "task_id": task_id,
                "priority": -priority  # Converte de volta para prioridade positiva
            })
            temp_queue.put((priority, task_id))
            
        # Restaura a fila original
        while not temp_queue.empty():
            task_queue.put(temp_queue.get())
            
        return {
            "queue_length": len(queue_items),
            "tasks": queue_items
        }

@app.get("/metrics")
async def get_metrics(db: Session = Depends(get_db)):
    """Retorna métricas detalhadas do sistema"""
    try:
        # Coleta métricas do sistema
        system_metrics = {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent,
            "active_tasks": len(active_tasks)
        }
        
        # Coleta métricas do browser
        browser_metrics = browser_manager.get_metrics()
        
        # Coleta métricas históricas
        last_hour = datetime.utcnow() - timedelta(hours=1)
        historical_metrics = db.query(Metric).filter(
            Metric.timestamp >= last_hour
        ).order_by(Metric.timestamp.desc()).all()
        
        return {
            "system": system_metrics,
            "browser": browser_metrics,
            "historical": [
                {
                    "timestamp": m.timestamp.isoformat(),
                    "metrics": json.loads(m.metrics)
                } for m in historical_metrics
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics/errors")
async def get_error_metrics(db: Session = Depends(get_db)):
    """Retorna métricas de erros"""
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks", response_model=List[TaskResponse])
async def get_tasks(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
        return tasks
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks", response_model=TaskResponse)
async def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    try:
        db_task = Task(
            task=task.task,
            config=task.config,
            status="pending",
            priority=task.priority,
            max_retries=task.max_retries,
            timeout=task.timeout,
            tags=task.tags,
            metadata=task.metadata
        )
        db.add(db_task)
        await db.commit()
        await db.refresh(db_task)
        return db_task
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: int, task: TaskUpdate, db: Session = Depends(get_db)):
    try:
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        for key, value in task.dict(exclude_unset=True).items():
            setattr(db_task, key, value)
            
        await db.commit()
        await db.refresh(db_task)
        return db_task
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    try:
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
            
        db.delete(db_task)
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/browser-sessions", response_model=BrowserSessionResponse)
async def create_browser_session(session: BrowserSessionCreate, db: Session = Depends(get_db)):
    try:
        db_session = await create_browser_session(db=db, session=session)
        return db_session
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser-sessions", response_model=List[BrowserSessionResponse])
async def read_browser_sessions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    try:
        sessions = await get_browser_sessions(db, skip=skip, limit=limit)
        return sessions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser-sessions/{session_id}", response_model=BrowserSessionResponse)
async def read_browser_session(session_id: int, db: Session = Depends(get_db)):
    try:
        db_session = await get_browser_session(db, session_id=session_id)
        if not db_session:
            raise HTTPException(status_code=404, detail="Browser session not found")
        return db_session
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}/browser-sessions", response_model=List[BrowserSessionResponse])
async def read_task_browser_sessions(task_id: int, db: Session = Depends(get_db)):
    try:
        sessions = await get_browser_sessions_by_task(db, task_id=task_id)
        return sessions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Tratamento global de exceções"""
    logger.error(f"Erro não tratado: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

@app.get("/health")
async def health_check():
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

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_by_id(task_id: int, db: Session = Depends(get_db)):
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

@app.post("/tasks/", response_model=TaskResponse)
async def create_new_task(task: TaskCreate, db: Session = Depends(get_db)):
    db_task = await create_task(db, task)
    return TaskResponse(
        id=db_task.id,
        status=db_task.status,
        priority=db_task.priority,
        result=db_task.result,
        error=db_task.error,
        created_at=db_task.created_at,
        completed_at=db_task.completed_at
    )

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_existing_task(task_id: int, task: TaskUpdate, db: Session = Depends(get_db)):
    db_task = await update_task(db, task_id, task)
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(
        id=db_task.id,
        status=db_task.status,
        priority=db_task.priority,
        result=db_task.result,
        error=db_task.error,
        created_at=db_task.created_at,
        completed_at=db_task.completed_at
    )

@app.delete("/tasks/{task_id}")
async def delete_existing_task(task_id: int, db: Session = Depends(get_db)):
    success = await delete_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}

@app.get("/browser-sessions/", response_model=List[BrowserSessionResponse])
async def list_browser_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
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

@app.get("/browser-sessions/{session_id}", response_model=BrowserSessionResponse)
async def get_browser_session_by_id(session_id: int, db: Session = Depends(get_db)):
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

@app.get("/tasks/{task_id}/browser-sessions/", response_model=List[BrowserSessionResponse])
async def get_task_browser_sessions(task_id: int, db: Session = Depends(get_db)):
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