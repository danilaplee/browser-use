from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class TaskBase(BaseModel):
    task: str
    config: Optional[Dict[str, Any]] = None
    status: Optional[str] = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    priority: Optional[float] = 0.0
    retry_count: Optional[int] = 0
    max_retries: Optional[int] = 3
    timeout: Optional[int] = 300
    tags: Optional[Dict[str, Any]] = None
    task_metadata: Optional[Dict[str, Any]] = None

class TaskCreate(TaskBase):
    pass

class TaskUpdate(TaskBase):
    pass

class TaskResponse(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SessionBase(BaseModel):
    task_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str
    error: Optional[str] = None

class SessionCreate(SessionBase):
    pass

class SessionUpdate(SessionBase):
    pass

class SessionResponse(SessionBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class BrowserMetricsBase(BaseModel):
    session_id: int
    cpu_usage: float
    memory_usage: float
    network_usage: float

class BrowserMetricsCreate(BrowserMetricsBase):
    pass

class BrowserMetricsResponse(BrowserMetricsBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

class MetricsBase(BaseModel):
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_usage: float

class MetricsCreate(MetricsBase):
    pass

class MetricsResponse(MetricsBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

class SystemStatus(BaseModel):
    cpu_usage: float
    memory_usage: float
    active_tasks: int
    queued_tasks: int
    completed_tasks: int
    failed_tasks: int
    max_concurrent_tasks: int
    available_slots: int

class BrowserSessionBase(BaseModel):
    task_id: int
    session_id: str
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class BrowserSessionCreate(BrowserSessionBase):
    pass

class BrowserSession(BrowserSessionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class TaskResponse(BaseModel):
    """Schema para resposta de tarefa"""
    id: int = Field(..., description="ID da tarefa")
    status: str = Field(..., description="Status da tarefa")
    priority: float = Field(..., description="Prioridade da tarefa")
    result: Optional[str] = Field(None, description="Resultado da tarefa")
    error: Optional[str] = Field(None, description="Mensagem de erro")
    created_at: datetime = Field(..., description="Data de criação")
    completed_at: Optional[datetime] = Field(None, description="Data de conclusão") 