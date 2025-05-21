from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, TypeDecorator
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.dialects.postgresql import JSONB, UUID
import os
from dotenv import load_dotenv
import logging
from logging_config import setup_logging, log_info, log_error, log_debug
from datetime import datetime
from sqlalchemy.sql import select
from contextlib import contextmanager
import json
import uuid

# Logging configuration
logger = logging.getLogger('browser-use.database')

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./browser_use.db")

log_info(logger, "Initializing database connection", {
    "database_url": DATABASE_URL,
    "type": "SQLite"
})

# Database setup
engine = create_engine(
    DATABASE_URL
    # connect_args={"check_same_thread": False}  # Required for SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Classes to convert JSON to string and vice versa (required for SQLite)
class JSONEncodedDict(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return None

# Models
class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task = Column(String, nullable=False)
    config = Column(JSONB, nullable=True)  # Using JSONEncodedDict
    status = Column(String, nullable=False)
    result = Column(JSONB, nullable=True)  # Using JSONEncodedDict
    error = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

# Function to get database session
@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()

# Function to initialize database
def init_db():
    log_info(logger, "Initializing database")
    try:
        Base.metadata.create_all(bind=engine)
        log_info(logger, "Database tables created successfully")
    except Exception as e:
        log_error(logger, "Error initializing database", {
            "error": str(e)
        }, exc_info=True)
        raise

# CRUD functions for Task (synchronous version)
def create_task(db: Session, task_data: dict) -> Task:
    try:
        task = Task(
            task=task_data["task"],
            config=task_data.get("config"),
            status="pending",
            created_at=datetime.utcnow()
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    except Exception as e:
        log_error(logger, "Error creating task", {
            "error": str(e)
        }, exc_info=True)
        raise

def get_task(db: Session, task_id: int) -> Task:
    try:
        return db.query(Task).filter(Task.id == task_id).first()
    except Exception as e:
        log_error(logger, "Error getting task", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

def update_task(db: Session, task_id: int, task_data: dict) -> Task:
    try:
        task = get_task(db, task_id)
        if task:
            for key, value in task_data.items():
                setattr(task, key, value)
            db.commit()
            db.refresh(task)
        return task
    except Exception as e:
        log_error(logger, "Error updating task", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

def get_tasks(db: Session, skip: int = 0, limit: int = 100) -> list[Task]:
    try:
        return db.query(Task).offset(skip).limit(limit).all()
    except Exception as e:
        log_error(logger, "Error listing tasks", {
            "error": str(e)
        }, exc_info=True)
        raise

def get_pending_tasks(db: Session, skip: int = 0, limit: int = 100) -> list[Task]:
    try:
        return db.query(Task).where(Task.status == "pending").offset(skip).limit(limit).all()
    except Exception as e:
        log_error(logger, "Error listing tasks", {
            "error": str(e)
        }, exc_info=True)
        raise


def delete_task(db: Session, task_id: int) -> bool:
    """Remove a task from database"""
    try:
        task = get_task(db, task_id)
        if task:
            db.delete(task)
            db.commit()
            return True
        return False
    except Exception as e:
        log_error(logger, "Error deleting task", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise