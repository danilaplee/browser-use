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
        raise
    finally:
        running_tasks.remove(task_id)

# Função para processar a fila
async def process_queue():
    while True:
        try:
            if len(running_tasks) < MAX_CONCURRENT_TASKS:
                task_id, task, config = await task_queue.get()
                running_tasks.add(task_id)
                asyncio.create_task(execute_task(task_id, task, config, next(get_db())))
            await asyncio.sleep(1)
        except Exception as e:
            log_error(logger, f"Erro ao processar fila: {str(e)}")
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
async def run_task(request: TaskRequest, db: Session = Depends(get_db)):
    """Executa uma nova tarefa de automação"""
    try:
        # Criar nova tarefa no banco de dados
        db_task = Task(
            task=request.task,
            config=json.dumps({
                "llm_config": request.llm_config,
                "browser_config": request.browser_config,
                "max_steps": request.max_steps,
                "use_vision": request.use_vision
            }),
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
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: int, db: Session = Depends(get_db)):
    """Obtém o status de uma tarefa"""
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Tarefa não encontrada")

        return TaskStatus(
            id=task.id,
            status=task.status,
            result=json.loads(task.result) if task.result else None,
            error=task.error,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at
        )

    except Exception as e:
        log_error(logger, f"Erro ao obter status da tarefa: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/metrics", response_model=SystemMetrics)
async def get_metrics():
    """Obtém métricas do sistema"""
    try:
        max_tasks = calculate_max_tasks()
        return SystemMetrics(
            cpu_usage=psutil.cpu_percent(),
            memory_usage=psutil.virtual_memory().percent,
            active_tasks=len(running_tasks),
            queued_tasks=task_queue.qsize(),
            max_concurrent_tasks=max_tasks,
            available_slots=max_tasks - len(running_tasks)
        )

    except Exception as e:
        log_error(logger, f"Erro ao obter métricas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)) 