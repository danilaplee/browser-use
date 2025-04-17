from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, JSON, Float
import os
from dotenv import load_dotenv
import asyncio
import logging
from logging_config import setup_logging, log_info, log_error, log_debug

# Configuração de logging
logger = logging.getLogger('browser-use.database')

load_dotenv()

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://")

log_info(logger, "Inicializando conexão com o banco de dados", {
    "database_url": SQLALCHEMY_DATABASE_URL.replace(os.getenv("POSTGRES_PASSWORD", ""), "****")
})

# Configuração do banco de dados assíncrono
engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

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

# Função para obter sessão do banco de dados
async def get_db():
    log_debug(logger, "Obtendo nova sessão do banco de dados")
    async with async_session_maker() as session:
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

# Inicializa o banco de dados de forma assíncrona
async def init_db_async():
    log_info(logger, "Iniciando inicialização assíncrona do banco de dados")
    await init_db()

# Executa a inicialização do banco de dados
def init_db_sync():
    log_info(logger, "Iniciando inicialização síncrona do banco de dados")
    try:
        asyncio.run(init_db_async())
        log_info(logger, "Banco de dados inicializado com sucesso")
    except Exception as e:
        log_error(logger, "Erro ao inicializar banco de dados de forma síncrona", {
            "error": str(e)
        }, exc_info=True)
        raise 