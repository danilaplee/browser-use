from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./browser_use.db")

# Configuração do banco de dados
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

# Cria as tabelas
Base.metadata.create_all(bind=engine)

# Função para obter sessão do banco de dados
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine) 