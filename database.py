from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, DateTime, JSON, Float
import os
from dotenv import load_dotenv
import asyncio
import logging
from logging_config import setup_logging, log_info, log_error, log_debug
from datetime import datetime
from sqlalchemy.sql import select
from typing import AsyncGenerator

# Configuração de logging
logger = logging.getLogger('browser-use.database')

load_dotenv()

# Converte a URL do banco de dados para usar o driver asyncpg
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL não está definida no arquivo .env")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://")

log_info(logger, "Inicializando conexão com o banco de dados", {
    "database_url": DATABASE_URL.replace(os.getenv("POSTGRES_PASSWORD", ""), "****")
})

# Configuração do banco de dados assíncrono
engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Modelos
class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task = Column(String, nullable=False)
    config = Column(JSON, nullable=True)
    status = Column(String, nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False)

class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)

# Função para obter sessão do banco de dados
async def get_db():
    log_debug(logger, "Obtendo nova sessão do banco de dados")
    async with async_session() as session:
        try:
            yield session
            await session.commit()
            log_debug(logger, "Sessão do banco de dados commitada com sucesso")
        except Exception as e:
            log_error(logger, "Erro ao commitar sessão do banco de dados", {
                "error": str(e)
            }, exc_info=True)
            await session.rollback()
            raise
        finally:
            await session.close()
            log_debug(logger, "Sessão do banco de dados fechada")

# Função para inicializar o banco
async def init_db():
    log_info(logger, "Inicializando banco de dados")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            log_info(logger, "Tabelas do banco de dados criadas com sucesso")
    except Exception as e:
        log_error(logger, "Erro ao inicializar banco de dados", {
            "error": str(e)
        }, exc_info=True)
        raise

# Funções CRUD para Task
async def create_task(db: AsyncSession, task_data: dict) -> Task:
    """Cria uma nova tarefa no banco de dados"""
    try:
        task = Task(
            task=task_data["task"],
            config=task_data.get("config"),
            status="pending",
            created_at=datetime.utcnow()
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task
    except Exception as e:
        log_error(logger, "Erro ao criar tarefa", {
            "error": str(e)
        }, exc_info=True)
        raise

async def get_task(db: AsyncSession, task_id: int) -> Task:
    """Obtém uma tarefa pelo ID"""
    try:
        return await db.get(Task, task_id)
    except Exception as e:
        log_error(logger, "Erro ao obter tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

async def update_task(db: AsyncSession, task_id: int, task_data: dict) -> Task:
    """Atualiza uma tarefa existente"""
    try:
        task = await get_task(db, task_id)
        if task:
            for key, value in task_data.items():
                setattr(task, key, value)
            await db.commit()
            await db.refresh(task)
        return task
    except Exception as e:
        log_error(logger, "Erro ao atualizar tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

async def delete_task(db: AsyncSession, task_id: int) -> bool:
    """Remove uma tarefa do banco de dados"""
    try:
        task = await get_task(db, task_id)
        if task:
            await db.delete(task)
            await db.commit()
            return True
        return False
    except Exception as e:
        log_error(logger, "Erro ao deletar tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

async def get_tasks(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Task]:
    """Lista todas as tarefas com paginação"""
    try:
        result = await db.execute(select(Task).offset(skip).limit(limit))
        return result.scalars().all()
    except Exception as e:
        log_error(logger, "Erro ao listar tarefas", {
            "error": str(e)
        }, exc_info=True)
        raise

# Funções para Session
async def get_sessions(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Session]:
    """Lista todas as sessões com paginação"""
    try:
        result = await db.execute(select(Session).offset(skip).limit(limit))
        return result.scalars().all()
    except Exception as e:
        log_error(logger, "Erro ao listar sessões", {
            "error": str(e)
        }, exc_info=True)
        raise

async def get_session(db: AsyncSession, session_id: int) -> Session:
    """Obtém uma sessão pelo ID"""
    try:
        return await db.get(Session, session_id)
    except Exception as e:
        log_error(logger, "Erro ao obter sessão", {
            "session_id": session_id,
            "error": str(e)
        }, exc_info=True)
        raise

async def get_task_sessions(db: AsyncSession, task_id: int) -> list[Session]:
    """Obtém todas as sessões de uma tarefa"""
    try:
        result = await db.execute(select(Session).where(Session.task_id == task_id))
        return result.scalars().all()
    except Exception as e:
        log_error(logger, "Erro ao obter sessões da tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise 