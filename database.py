from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Float, TypeDecorator
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
from dotenv import load_dotenv
import logging
from logging_config import setup_logging, log_info, log_error, log_debug
from datetime import datetime
from sqlalchemy.sql import select
from contextlib import contextmanager
import json

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

    id = Column(Integer, primary_key=True, index=True)
    task = Column(String, nullable=False)
    config = Column(JSONEncodedDict, nullable=True)  # Using JSONEncodedDict
    status = Column(String, nullable=False)
    result = Column(JSONEncodedDict, nullable=True)  # Using JSONEncodedDict
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

# Functions for Session
def get_sessions(db: Session, skip: int = 0, limit: int = 100) -> list[Session]:
    """List all sessions with pagination"""
    try:
        result = db.query(Session).offset(skip).limit(limit).all()
        return result
    except Exception as e:
        log_error(logger, "Error listing sessions", {
            "error": str(e)
        }, exc_info=True)
        raise

def get_session(db: Session, session_id: int) -> Session:
    """Get a session by ID"""
    try:
        return db.query(Session).filter(Session.id == session_id).first()
    except Exception as e:
        log_error(logger, "Error getting session", {
            "session_id": session_id,
            "error": str(e)
        }, exc_info=True)
        raise

def get_task_sessions(db: Session, task_id: int) -> list[Session]:
    """Get all sessions for a task"""
    try:
        result = db.query(Session).filter(Session.task_id == task_id).all()
        return result
    except Exception as e:
        log_error(logger, "Error getting task sessions", {
            "task_id": task_id,
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