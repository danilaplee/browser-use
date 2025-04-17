from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, FastAPI, Request
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
from database import get_db, Task, Metric, init_db, create_task, get_task, update_task, delete_task, get_tasks, get_sessions, get_session, get_task_sessions
import json
import os
import statistics
import httpx
import logging
from browser import BrowserManager
from config import settings
from models import BrowserMetrics, TaskResponse, Session, SessionResponse, Metrics
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning
from fastapi.responses import JSONResponse
from schemas import TaskCreate, TaskResponse, SessionResponse, BrowserMetricsResponse, MetricsResponse, SystemStatus, TaskUpdate
from playwright.async_api import Browser, Page

# Configuração de logging
logger = logging.getLogger('browser-use.api')

router = APIRouter()
browser_manager = BrowserManager()

app = FastAPI()

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

@app.get("/metrics")
async def get_metrics():
    try:
        metrics = await collect_metrics()
        log_info(logger, "Métricas coletadas com sucesso")
        return metrics
    except Exception as e:
        log_error(logger, f"Erro ao coletar métricas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks")
async def list_tasks():
    try:
        tasks = await get_tasks()
        log_info(logger, f"Listadas {len(tasks)} tarefas")
        return tasks
    except Exception as e:
        log_error(logger, f"Erro ao listar tarefas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_by_id(task_id: str, db: AsyncSession = Depends(get_db)):
    try:
        task = await get_task(db, int(task_id))
        if not task:
            raise HTTPException(status_code=404, detail="Tarefa não encontrada")
        return task
    except Exception as e:
        log_error(logger, f"Erro ao recuperar tarefa {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks", response_model=TaskResponse)
async def create_new_task(task: TaskCreate, db: AsyncSession = Depends(get_db)):
    try:
        db_task = await create_task(db, task.dict())
        return db_task
    except Exception as e:
        log_error(logger, f"Erro ao criar tarefa: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_existing_task(task_id: str, task: TaskUpdate, db: AsyncSession = Depends(get_db)):
    try:
        updated_task = await update_task(db, int(task_id), task.dict())
        if not updated_task:
            log_warning(logger, f"Tarefa não encontrada para atualização: {task_id}")
            raise HTTPException(status_code=404, detail="Tarefa não encontrada")
        log_info(logger, f"Tarefa atualizada: {task_id}")
        return TaskResponse.from_orm(updated_task)
    except Exception as e:
        log_error(logger, f"Erro ao atualizar tarefa {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
async def delete_existing_task(task_id: str):
    try:
        success = await delete_task(task_id)
        if not success:
            log_warning(logger, f"Tarefa não encontrada para exclusão: {task_id}")
            raise HTTPException(status_code=404, detail="Tarefa não encontrada")
        log_info(logger, f"Tarefa excluída: {task_id}")
        return {"message": "Tarefa excluída com sucesso"}
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, f"Erro ao excluir tarefa {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    try:
        sessions = await get_sessions(db)
        log_info(logger, f"Listadas {len(sessions)} sessões")
        return sessions
    except Exception as e:
        log_error(logger, f"Erro ao listar sessões: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_by_id(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        session = await get_session(db, int(session_id))
        if not session:
            log_warning(logger, f"Sessão não encontrada: {session_id}")
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        log_info(logger, f"Sessão recuperada: {session_id}")
        return session
    except Exception as e:
        log_error(logger, f"Erro ao recuperar sessão {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}/sessions", response_model=List[SessionResponse])
async def get_sessions_by_task(task_id: str, db: AsyncSession = Depends(get_db)):
    try:
        sessions = await get_task_sessions(db, int(task_id))
        log_info(logger, f"Listadas {len(sessions)} sessões para a tarefa {task_id}")
        return sessions
    except Exception as e:
        log_error(logger, f"Erro ao listar sessões da tarefa {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log_error(logger, f"Erro não tratado: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Ocorreu um erro interno no servidor"}
    )

async def execute_task(
    task_id: str,
    task: Task,
    browser: Browser,
    page: Page,
    db: AsyncSession
):
    try:
        log_info(logger, f"Iniciando execução da tarefa {task_id}")
        
        # Criar nova sessão
        session = Session(
            task_id=task_id,
            start_time=datetime.now(),
            status="running"
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        log_info(logger, f"Sessão {session.session_id} criada para a tarefa {task_id}")
        
        try:
            # Executar ações
            for action in task.actions:
                log_info(logger, f"Executando ação: {action.action_type}")
                
                if action.action_type == "navigate":
                    await page.goto(action.url)
                    log_info(logger, f"Navegado para {action.url}")
                    
                elif action.action_type == "click":
                    await page.click(action.selector)
                    log_info(logger, f"Clicado no elemento {action.selector}")
                    
                elif action.action_type == "type":
                    await page.type(action.selector, action.text)
                    log_info(logger, f"Digitado texto no elemento {action.selector}")
                    
                elif action.action_type == "wait":
                    await page.wait_for_selector(action.selector)
                    log_info(logger, f"Aguardado elemento {action.selector}")
                    
                elif action.action_type == "screenshot":
                    screenshot_path = f"screenshots/{session.session_id}_{action.name}.png"
                    await page.screenshot(path=screenshot_path)
                    log_info(logger, f"Capturado screenshot: {screenshot_path}")
                    
                elif action.action_type == "extract":
                    element = await page.query_selector(action.selector)
                    if element:
                        text = await element.text_content()
                        log_info(logger, f"Extraído texto do elemento {action.selector}")
                    else:
                        log_warning(logger, f"Elemento não encontrado: {action.selector}")
                        
                # Coletar métricas após cada ação
                metrics = await collect_metrics()
                metrics.session_id = session.session_id
                db.add(metrics)
                await db.commit()
                
            # Atualizar status da sessão
            session.status = "completed"
            session.end_time = datetime.now()
            await db.commit()
            
            log_info(logger, f"Tarefa {task_id} concluída com sucesso")
            
        except Exception as e:
            session.status = "failed"
            session.end_time = datetime.now()
            session.error = str(e)
            await db.commit()
            
            log_error(logger, f"Erro na execução da tarefa {task_id}: {str(e)}")
            raise
            
    except Exception as e:
        log_error(logger, f"Erro fatal na execução da tarefa {task_id}: {str(e)}")
        raise

async def collect_metrics() -> dict:
    """Coleta métricas do sistema e do navegador"""
    try:
        log_info(logger, "Iniciando coleta de métricas")
        
        # Coletar métricas do sistema
        system_metrics = await get_system_metrics()
        
        # Coletar métricas do navegador
        browser_metrics = await get_browser_metrics()
        
        # Combinar métricas
        metrics = {
            "system": system_metrics,
            "browser": browser_metrics,
            "timestamp": datetime.now().isoformat()
        }
        
        log_info(logger, "Métricas coletadas com sucesso")
        return metrics
        
    except Exception as e:
        log_error(logger, f"Erro ao coletar métricas: {str(e)}")
        raise

async def collect_metrics_periodically():
    """Coleta métricas periodicamente e salva no banco de dados"""
    try:
        log_info(logger, "Iniciando coleta periódica de métricas")
        
        while True:
            try:
                metrics = await collect_metrics()
                db.add(metrics)
                await db.commit()
                
                log_info(logger, "Métricas coletadas e salvas com sucesso")
                
            except Exception as e:
                log_error(logger, f"Erro ao coletar métricas periodicamente: {str(e)}")
                
            await asyncio.sleep(60)  # Coletar a cada 1 minuto
            
    except Exception as e:
        log_error(logger, f"Erro fatal na coleta periódica de métricas: {str(e)}")
        raise

async def get_system_metrics() -> dict:
    """Coleta métricas do sistema"""
    try:
        log_info(logger, "Iniciando coleta de métricas do sistema")
        
        # Coletar métricas de CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        
        # Coletar métricas de memória
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # Coletar métricas de disco
        disk = psutil.disk_usage('/')
        disk_io = psutil.disk_io_counters()
        
        metrics = {
            "cpu": {
                "percent": cpu_percent,
                "count": cpu_count,
                "frequency": {
                    "current": cpu_freq.current,
                    "min": cpu_freq.min,
                    "max": cpu_freq.max
                }
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "percent": memory.percent,
                "swap": {
                    "total": swap.total,
                    "used": swap.used,
                    "free": swap.free,
                    "percent": swap.percent
                }
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent,
                "io": {
                    "read_bytes": disk_io.read_bytes,
                    "write_bytes": disk_io.write_bytes,
                    "read_count": disk_io.read_count,
                    "write_count": disk_io.write_count
                }
            }
        }
        
        log_info(logger, "Métricas do sistema coletadas com sucesso")
        return metrics
        
    except Exception as e:
        log_error(logger, f"Erro ao coletar métricas do sistema: {str(e)}")
        raise

async def get_browser_metrics() -> dict:
    """Coleta métricas do navegador"""
    try:
        log_info(logger, "Iniciando coleta de métricas do navegador")
        
        # Obter lista de processos do navegador
        browser_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                if 'chrome' in proc.info['name'].lower() or 'firefox' in proc.info['name'].lower():
                    browser_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Calcular métricas totais
        total_memory = sum(proc.info['memory_info'].rss for proc in browser_processes)
        total_cpu = sum(proc.info['cpu_percent'] for proc in browser_processes)
        
        metrics = {
            "process_count": len(browser_processes),
            "total_memory_usage": total_memory,
            "total_cpu_usage": total_cpu,
            "processes": [
                {
                    "pid": proc.info['pid'],
                    "name": proc.info['name'],
                    "memory_usage": proc.info['memory_info'].rss,
                    "cpu_usage": proc.info['cpu_percent']
                }
                for proc in browser_processes
            ]
        }
        
        log_info(logger, "Métricas do navegador coletadas com sucesso")
        return metrics
        
    except Exception as e:
        log_error(logger, f"Erro ao coletar métricas do navegador: {str(e)}")
        raise 