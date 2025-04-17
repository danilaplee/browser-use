from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
import psutil
import json
import logging
from sqlalchemy.orm import Session
from database import get_db, Task
from logging_config import setup_logging, log_info, log_error
from browser import BrowserManager
import aiohttp
import traceback

# Configuração de logging
logger = logging.getLogger('browser-use.api')

router = APIRouter()
browser_manager = BrowserManager()

# Configurações do sistema
MAX_CONCURRENT_TASKS = 2  # Será ajustado dinamicamente baseado nos recursos
MAX_QUEUE_SIZE = 10

# Fila de tasks
task_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
running_tasks = set()

# Modelos Pydantic
class TaskRequest(BaseModel):
    task: str
    llm_config: Dict[str, Any]
    browser_config: Optional[Dict[str, Any]] = None
    max_steps: int = 20
    use_vision: bool = True

class TaskStatus(BaseModel):
    id: int
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class SystemMetrics(BaseModel):
    cpu_usage: float
    memory_usage: float
    active_tasks: int
    queued_tasks: int
    max_concurrent_tasks: int
    available_slots: int

# URL do webhook para envio de erros
ERROR_WEBHOOK_URL = "https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/browser-use-vra-handler"

async def send_error_to_webhook(error: str, context: str, task_id: Optional[int] = None):
    """Envia informações de erro para o webhook"""
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
                    logger.error(f"Falha ao enviar erro para webhook: {response.status}")
    except Exception as e:
        logger.error(f"Erro ao enviar para webhook: {str(e)}")

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

# Função para executar uma task
async def execute_task(task_id: int, task: str, config: Dict[str, Any], db: Session):
    try:
        # Atualizar status para running
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if db_task:
            db_task.status = "running"
            db_task.started_at = datetime.utcnow()
            db.commit()

        # Executar a task
        result = await browser_manager.execute_task(task, config)

        # Atualizar status para completed
        if db_task:
            db_task.status = "completed"
            db_task.result = json.dumps(result)
            db_task.completed_at = datetime.utcnow()
            db.commit()

    except Exception as e:
        # Atualizar status para failed
        if db_task:
            db_task.status = "failed"
            db_task.error = str(e)
            db_task.completed_at = datetime.utcnow()
            db.commit()
        await send_error_to_webhook(str(e), "execute_task", task_id)
        raise
    finally:
        running_tasks.remove(task_id)
        db.close()

# Função para processar a fila
async def process_queue():
    while True:
        try:
            if len(running_tasks) < MAX_CONCURRENT_TASKS:
                task_id, task, config = await task_queue.get()
                running_tasks.add(task_id)
                
                # Criar uma nova sessão do banco de dados para cada tarefa
                db = next(get_db())
                try:
                    asyncio.create_task(execute_task(task_id, task, config, db))
                except Exception as e:
                    log_error(logger, f"Erro ao criar tarefa: {str(e)}")
                    await send_error_to_webhook(str(e), "process_queue", task_id)
                    running_tasks.remove(task_id)
                    db.close()
                
            await asyncio.sleep(1)
        except Exception as e:
            log_error(logger, f"Erro ao processar fila: {str(e)}")
            await send_error_to_webhook(str(e), "process_queue")
            await asyncio.sleep(1)

# Iniciar processamento da fila
asyncio.create_task(process_queue())

# Função para coletar métricas periodicamente
async def collect_metrics_periodically():
    """Coleta métricas do sistema periodicamente e ajusta o limite de tarefas simultâneas"""
    while True:
        try:
            # Atualizar o limite de tarefas simultâneas baseado nos recursos
            global MAX_CONCURRENT_TASKS
            MAX_CONCURRENT_TASKS = calculate_max_tasks()
            
            # Log das métricas atuais
            log_info(logger, "Métricas do sistema atualizadas", {
                "max_concurrent_tasks": MAX_CONCURRENT_TASKS,
                "active_tasks": len(running_tasks),
                "queued_tasks": task_queue.qsize(),
                "cpu_usage": psutil.cpu_percent(),
                "memory_usage": psutil.virtual_memory().percent
            })
            
            # Aguardar 30 segundos antes da próxima coleta
            await asyncio.sleep(30)
            
        except Exception as e:
            log_error(logger, f"Erro ao coletar métricas: {str(e)}")
            await asyncio.sleep(30)  # Aguardar mesmo em caso de erro

# Iniciar coleta periódica de métricas
asyncio.create_task(collect_metrics_periodically())

@router.post("/run")
async def run_task(request: TaskRequest):
    """Executa uma nova tarefa de automação"""
    try:
        # Criar nova tarefa no banco de dados
        with get_db() as db:
            db_task = Task(
                task=request.task,
                config={
                    "llm_config": request.llm_config,
                    "browser_config": request.browser_config,
                    "max_steps": request.max_steps,
                    "use_vision": request.use_vision
                },
                status="pending",
                created_at=datetime.utcnow()
            )
            db.add(db_task)
            db.commit()
            db.refresh(db_task)

            # Adicionar à fila
            await task_queue.put((db_task.id, request.task, request.dict()))

            return {"task_id": db_task.id}

    except Exception as e:
        log_error(logger, f"Erro ao executar tarefa: {str(e)}")
        await send_error_to_webhook(str(e), "run_task")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{task_id}")
async def get_task_status(task_id: int):
    """Retorna o status de uma tarefa"""
    try:
        with get_db() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="Tarefa não encontrada")

            return {
                "task_id": task.id,
                "status": task.status,
                "result": task.result if task.status == "completed" else None,
                "error": task.error if task.status == "failed" else None
            }

    except Exception as e:
        log_error(logger, f"Erro ao obter status da tarefa: {str(e)}")
        await send_error_to_webhook(str(e), "get_task_status", task_id)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/metrics")
async def get_metrics():
    """Retorna métricas do sistema"""
    try:
        with get_db() as db:
            # Obtém estatísticas do banco de dados
            total_tasks = db.query(Task).count()
            completed_tasks = db.query(Task).filter(Task.status == "completed").count()
            failed_tasks = db.query(Task).filter(Task.status == "failed").count()
            running_tasks = db.query(Task).filter(Task.status == "running").count()

            # Obtém métricas do sistema
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
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
                    "queued": len(task_queue),
                    "available_slots": MAX_CONCURRENT_TASKS - running_tasks
                }
            }

    except Exception as e:
        log_error(logger, f"Erro ao obter métricas: {str(e)}")
        await send_error_to_webhook(str(e), "get_metrics")
        raise HTTPException(status_code=500, detail=str(e)) 