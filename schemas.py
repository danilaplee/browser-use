from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class TaskBase(BaseModel):
    name: str
    description: Optional[str] = None
    url: str
    task_type: str
    task_config: Dict[str, Any]

class TaskCreate(BaseModel):
    """Schema para criação de tarefa"""
    task: str = Field(..., description="Instrução da tarefa")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configurações da tarefa")
    priority: float = Field(default=0.0, description="Prioridade da tarefa (maior = mais prioritária)")
    max_retries: int = Field(default=3, description="Número máximo de tentativas")
    timeout: int = Field(default=300, description="Timeout em segundos")
    tags: List[str] = Field(default_factory=list, description="Tags para categorização")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados adicionais")

class Task(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

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