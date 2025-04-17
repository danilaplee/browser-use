from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import asyncio
import psutil
import uuid
import time
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db, Task, Metric, init_db
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
async def collect_system_metrics(db: AsyncSession):
    metrics = Metric(
        name="system_metrics",
        value=json.dumps({
            "cpu_usage": psutil.cpu_percent(),
            "memory_usage": psutil.virtual_memory().percent,
            "active_tasks": len(running_tasks),
            "queued_tasks": task_queue.qsize(),
            "completed_tasks": await db.scalar(select(Task).where(Task.status == "completed").count()),
            "failed_tasks": await db.scalar(select(Task).where(Task.status == "failed").count())
        }),
        created_at=datetime.utcnow()
    )
    db.add(metrics)
    await db.commit()

# Função para enviar webhook
async def send_webhook(task: Task, error_type: str, error_message: str):
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "task_id": task.id,
                "task": task.task,
                "status": task.status,
                "error_type": error_type,
                "error_message": error_message,
                "created_at": task.created_at.isoformat(),
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "duration": (datetime.utcnow() - task.started_at).total_seconds() if task.started_at else None
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

# Endpoints
@router.post("/run")
async def run_task(
    task: str,
    config: Optional[dict] = None,
    db: AsyncSession = Depends(get_db)
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
        await db.commit()
        await db.refresh(db_task)

        # Executar tarefa em background
        asyncio.create_task(
            execute_task(
                db_task.id,
                task,
                config or {},
                db
            )
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
    db: AsyncSession = Depends(get_db)
):
    """Obtém o status de uma tarefa"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    
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
async def get_system_status(db: AsyncSession = Depends(get_db)):
    max_tasks = calculate_max_tasks()
    return SystemStatus(
        cpu_usage=psutil.cpu_percent(),
        memory_usage=psutil.virtual_memory().percent,
        active_tasks=len(running_tasks),
        queued_tasks=task_queue.qsize(),
        completed_tasks=await db.scalar(select(Task).where(Task.status == "completed").count()),
        failed_tasks=await db.scalar(select(Task).where(Task.status == "failed").count()),
        max_concurrent_tasks=max_tasks,
        available_slots=max_tasks - len(running_tasks)
    )

@router.get("/metrics")
async def get_metrics(
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Obtém as últimas métricas do sistema"""
    result = await db.execute(
        select(Metric)
        .order_by(Metric.created_at.desc())
        .limit(limit)
    )
    metrics = result.scalars().all()
    
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

async def execute_task(
    task_id: int,
    task: str,
    config: dict,
    db: AsyncSession
):
    """Executa uma tarefa de automação"""
    try:
        # Atualizar status da tarefa
        result = await db.execute(select(Task).where(Task.id == task_id))
        db_task = result.scalar_one_or_none()
        if not db_task:
            return
        
        db_task.status = "running"
        db_task.started_at = datetime.utcnow()
        await db.commit()

        # Executar tarefa usando o BrowserManager
        result = await browser_manager.execute_task(task, config)

        # Atualizar resultado da tarefa
        db_task.status = "completed"
        db_task.result = json.dumps(result)
        db_task.completed_at = datetime.utcnow()
        await db.commit()

    except Exception as e:
        # Atualizar erro da tarefa
        db_task.status = "failed"
        db_task.error = str(e)
        db_task.completed_at = datetime.utcnow()
        await db.commit()
        raise

async def collect_metrics_periodically():
    """Coleta métricas periodicamente"""
    while True:
        try:
            async with async_session_maker() as db:
                await collect_system_metrics(db)
            await asyncio.sleep(60)  # Coleta a cada minuto
        except Exception as e:
            logger.error(f"Erro ao coletar métricas: {str(e)}")
            await asyncio.sleep(60) 