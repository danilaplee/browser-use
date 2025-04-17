from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, APIRouter
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import asyncio
import psutil
import uuid
import time
import aiohttp
from sqlalchemy.orm import Session
from database import get_db, Task, TaskStatus, SystemMetrics, Metric
import json
import os
import statistics
import httpx
import logging
from browser import BrowserManager
from config import settings

# Configuração de logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = FastAPI()
router = APIRouter()
browser_manager = BrowserManager()

# Configurações do sistema
MAX_CONCURRENT_TASKS = 2  # Será ajustado dinamicamente baseado nos recursos
MAX_QUEUE_SIZE = 10
TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", 300))  # 5 minutos em segundos
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/browser-use-vra-handler")
NOTIFY_RUN_URL = os.getenv("NOTIFY_RUN_URL", "https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/notify-run")
STATUS_URL = os.getenv("STATUS_URL", "https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/status")

# Modelos Pydantic
class TaskRequest(BaseModel):
    task: str
    config: Optional[Dict[str, Any]] = None

class TaskResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class SystemStatus(BaseModel):
    cpu_usage: float
    memory_usage: float
    active_tasks: int
    queued_tasks: int
    completed_tasks: int
    failed_tasks: int
    max_concurrent_tasks: int
    available_slots: int

# Fila de tasks
task_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
running_tasks = set()

# Função para calcular recursos disponíveis
def calculate_max_tasks():
    cpu_count = psutil.cpu_count()
    memory = psutil.virtual_memory()
    
    # Considerando que cada task usa ~0.5 CPU e 400MB RAM
    max_by_cpu = int(cpu_count * 2)  # 2 tasks por CPU
    max_by_memory = int(memory.available / (400 * 1024 * 1024))  # 400MB por task
    
    # Limite máximo baseado em recursos
    max_tasks = min(max_by_cpu, max_by_memory)
    
    # Limite máximo absoluto de 32 tasks
    return min(max_tasks, 32)

# Função para coletar métricas do sistema
def collect_system_metrics(db: Session):
    metrics = SystemMetrics(
        cpu_usage=psutil.cpu_percent(),
        memory_usage=psutil.virtual_memory().percent,
        active_tasks=len(running_tasks),
        queued_tasks=task_queue.qsize(),
        completed_tasks=db.query(Task).filter(Task.status == TaskStatus.COMPLETED).count(),
        failed_tasks=db.query(Task).filter(Task.status == TaskStatus.FAILED).count()
    )
    db.add(metrics)
    db.commit()

# Função para enviar webhook
async def send_webhook(task: Task, error_type: str, error_message: str):
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "task_id": task.id,
                "task": task.task,
                "status": task.status.value,
                "error_type": error_type,
                "error_message": error_message,
                "created_at": task.created_at.isoformat(),
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "duration": (datetime.utcnow() - task.started_at).total_seconds() if task.started_at else None,
                "cpu_usage": task.cpu_usage,
                "memory_usage": task.memory_usage
            }
            
            async with session.post(WEBHOOK_URL, json=payload) as response:
                if response.status != 200:
                    print(f"Erro ao enviar webhook: {response.status}")
    except Exception as e:
        print(f"Erro ao enviar webhook: {str(e)}")

# Função para enviar notificação de nova task
async def send_new_task_notification(task: Task):
    """Envia notificação quando uma nova tarefa é adicionada."""
    try:
        payload = {
            "task_id": task.id,
            "task": task.task,
            "priority": task.priority,
            "created_at": task.created_at.isoformat(),
            "queue_position": task_queue.qsize() + 1,
            "estimated_wait_time": (task_queue.qsize() * 300)  # Estimativa de 5 minutos por task
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(NOTIFY_RUN_URL, json=payload)
            response.raise_for_status()
            logger.info(f"Notificação de nova tarefa enviada com sucesso: {task.id}")
    except Exception as e:
        logger.error(f"Erro ao enviar notificação de nova tarefa: {str(e)}")

# Função para calcular métricas horárias
async def calculate_hourly_metrics(db: Session):
    """Calcula e envia métricas horárias."""
    try:
        # Obtém métricas da última hora
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        metrics = db.query(SystemMetrics).filter(
            SystemMetrics.timestamp >= one_hour_ago
        ).all()

        if not metrics:
            return

        # Calcula médias e estatísticas
        cpu_usage = [m.cpu_usage for m in metrics]
        memory_usage = [m.memory_usage for m in metrics]
        active_tasks = [m.active_tasks for m in metrics]

        # Obtém tasks da última hora
        tasks = db.query(Task).filter(
            Task.created_at >= one_hour_ago
        ).all()

        # Calcula estatísticas das tasks
        completed_tasks = len([t for t in tasks if t.status == TaskStatus.COMPLETED])
        failed_tasks = len([t for t in tasks if t.status == TaskStatus.FAILED])
        avg_duration = statistics.mean([t.duration for t in tasks if t.duration is not None]) if tasks else 0

        # Prepara payload
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "cpu": {
                    "avg": statistics.mean(cpu_usage),
                    "max": max(cpu_usage),
                    "min": min(cpu_usage)
                },
                "memory": {
                    "avg": statistics.mean(memory_usage),
                    "max": max(memory_usage),
                    "min": min(memory_usage)
                },
                "tasks": {
                    "avg_concurrent": statistics.mean(active_tasks),
                    "max_concurrent": max(active_tasks),
                    "total_completed": completed_tasks,
                    "total_failed": failed_tasks,
                    "avg_duration": avg_duration
                }
            }
        }

        # Envia métricas
        async with httpx.AsyncClient() as client:
            response = await client.post(STATUS_URL, json=payload)
            response.raise_for_status()
            logger.info("Métricas horárias enviadas com sucesso")
    except Exception as e:
        logger.error(f"Erro ao calcular métricas horárias: {str(e)}")

# Endpoints
@router.post("/run")
async def run_task(
    task: str,
    config: Optional[dict] = None,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Executa uma tarefa de automação de navegador"""
    try:
        # Criar nova tarefa no banco de dados
        db_task = Task(
            task=task,
            config=json.dumps(config or {}),
            status="pending",
            created_at=datetime.utcnow()
        )
        db.add(db_task)
        db.commit()
        db.refresh(db_task)

        # Executar tarefa em background
        background_tasks.add_task(
            execute_task,
            db_task.id,
            task,
            config or {},
            db
        )

        return {
            "task_id": db_task.id,
            "status": "started",
            "message": "Tarefa iniciada com sucesso"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: int,
    db: Session = Depends(get_db)
):
    """Obtém o status de uma tarefa"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    
    return {
        "task_id": task.id,
        "status": task.status,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at
    }

@router.get("/status", response_model=SystemStatus)
async def get_system_status(db: Session = Depends(get_db)):
    max_tasks = calculate_max_tasks()
    return SystemStatus(
        cpu_usage=psutil.cpu_percent(),
        memory_usage=psutil.virtual_memory().percent,
        active_tasks=len(running_tasks),
        queued_tasks=task_queue.qsize(),
        completed_tasks=db.query(Task).filter(Task.status == TaskStatus.COMPLETED).count(),
        failed_tasks=db.query(Task).filter(Task.status == TaskStatus.FAILED).count(),
        max_concurrent_tasks=max_tasks,
        available_slots=max_tasks - len(running_tasks)
    )

@router.get("/metrics")
async def get_metrics(
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Obtém as últimas métricas do sistema"""
    metrics = db.query(Metric).order_by(Metric.created_at.desc()).limit(limit).all()
    return {
        "metrics": [
            {
                "name": m.name,
                "value": m.value,
                "created_at": m.created_at
            }
            for m in metrics
        ]
    }

# Worker que processa as tasks
async def process_task(task_id: str, db: Session):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    try:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        running_tasks.add(task_id)
        db.commit()

        # Inicia timer para timeout
        timeout_task = asyncio.create_task(asyncio.sleep(TASK_TIMEOUT))
        task_task = asyncio.create_task(run_browser_task(task.task))
        
        # Aguarda a primeira task completar
        done, pending = await asyncio.wait(
            [timeout_task, task_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancela a task pendente
        for task in pending:
            task.cancel()
        
        # Verifica se foi timeout
        if timeout_task in done:
            task.status = TaskStatus.FAILED
            task.error = f"Task excedeu o tempo limite de {TASK_TIMEOUT} segundos"
            await send_webhook(task, "timeout", task.error)
            return
        
        # Se chegou aqui, a task foi completada
        result = await task_task
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        task.result = result
        task.duration = (task.completed_at - task.started_at).total_seconds()
        
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        await send_webhook(task, "error", str(e))
    finally:
        running_tasks.remove(task_id)
        db.commit()

# Worker que gerencia a fila
async def queue_worker(db: Session):
    while True:
        max_tasks = calculate_max_tasks()
        if len(running_tasks) < max_tasks:
            try:
                task_id = await task_queue.get()
                asyncio.create_task(process_task(task_id, db))
            except asyncio.QueueEmpty:
                await asyncio.sleep(1)
        await asyncio.sleep(0.1)

# Inicia o worker ao iniciar a aplicação
@app.on_event("startup")
async def startup_event():
    db = next(get_db())
    asyncio.create_task(queue_worker(db))
    # Inicia coleta de métricas a cada 5 minutos
    asyncio.create_task(collect_metrics_periodically(db))

async def collect_metrics_periodically(db: Session):
    """Coleta métricas periodicamente e envia relatórios horários."""
    last_hourly_report = datetime.utcnow()
    
    while True:
        try:
            # Coleta métricas básicas
            cpu_usage = psutil.cpu_percent()
            memory_usage = psutil.virtual_memory().percent
            
            metric = SystemMetrics(
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
                active_tasks=len(running_tasks),
                queued_tasks=task_queue.qsize(),
                completed_tasks=db.query(Task).filter(Task.status == TaskStatus.COMPLETED).count(),
                failed_tasks=db.query(Task).filter(Task.status == TaskStatus.FAILED).count()
            )
            db.add(metric)
            db.commit()
            
            # Verifica se é hora de enviar o relatório horário
            now = datetime.utcnow()
            if (now - last_hourly_report).total_seconds() >= 3600:
                await calculate_hourly_metrics(db)
                last_hourly_report = now
            
            await asyncio.sleep(60)  # Coleta a cada minuto
        except Exception as e:
            logger.error(f"Erro ao coletar métricas: {str(e)}")
            await asyncio.sleep(60) 

async def execute_task(
    task_id: int,
    task: str,
    config: dict,
    db: Session
):
    """Executa uma tarefa de automação"""
    try:
        # Atualizar status da tarefa
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if not db_task:
            return
        
        db_task.status = "running"
        db_task.started_at = datetime.utcnow()
        db.commit()

        # Executar tarefa usando o BrowserManager
        result = await browser_manager.execute_task(task, config)

        # Atualizar resultado da tarefa
        db_task.status = "completed"
        db_task.result = json.dumps(result)
        db_task.completed_at = datetime.utcnow()
        db.commit()

    except Exception as e:
        # Atualizar erro da tarefa
        db_task.status = "failed"
        db_task.error = str(e)
        db_task.completed_at = datetime.utcnow()
        db.commit()
        raise 