import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_ollama import ChatOllama
from pydantic import SecretStr
from fastapi import HTTPException
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.runnables import RunnableConfig

# Logging configuration
logger = logging.getLogger('browser-use.settings')
load_dotenv()

# Data models
class BrowserConfigModel(BaseModel):
    headless: bool = True
    disable_security: bool = True
    extra_chromium_args: List[str] = []

class ModelConfig(BaseModel):
    provider: str = Field(..., description="Model provider: openai, azure")
    model_name: str = Field(..., description="Model name to be used")
    api_key: Optional[str] = Field(None, description="API key for the provider (if needed)")
    azure_endpoint: Optional[str] = Field(None, description="Endpoint for Azure OpenAI (if provider=azure)")
    azure_api_version: Optional[str] = Field(None, description="Azure OpenAI API version (if provider=azure)")
    temperature: float = Field(0.5, description="Generation temperature (0.0 to 1.0)")
    base_url: Optional[str] = Field(None, description="api base url")


SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./browser_use.db")
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "9000"))
API_DEBUG = os.getenv("API_DEBUG", "False").lower() == "true"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "True").lower() == "true"
BROWSER_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT", "30000")) 

class TaskRequest(BaseModel):
    task: str
    llm_config: ModelConfig
    browser_config: Optional[BrowserConfigModel] = None
    max_steps: int = 20
    use_vision: bool = True
    generate_gif: bool = False
    max_failures: int = 3
    memory_interval: int = 10
    planner_interval: int = 1

class AgentResponse(BaseModel):
    task: str
    result: str
    success: bool
    steps_executed: int
    error: Optional[str] = None
    videopath: Optional[str] = None

# Function to get LLM based on configuration
def get_llm(model_config: ModelConfig):
    try:
        provider = model_config.provider.lower()
        log_info(logger, "Initializing LLM", {
            "provider": provider,
            "model": model_config.model_name
        })
        
        if provider == "openai":
            return ChatOpenAI(
                model=model_config.model_name,
                temperature=model_config.temperature,
                api_key=model_config.api_key or os.getenv("OPENAI_API_KEY")
            )
        elif provider == "deepseek":
            return ChatOpenAI(
                base_url='https://api.deepseek.com/v1',
                model=model_config.model_name or 'deepseek-chat',
                api_key=model_config.api_key or os.getenv("DEEPSEEK_API_KEY"),
            )
        elif provider == "azure":
            return AzureChatOpenAI(
                model=model_config.model_name,
                temperature=model_config.temperature,
                api_key=SecretStr(model_config.api_key or os.getenv("AZURE_OPENAI_KEY", "")),
                azure_endpoint=model_config.azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                api_version=model_config.azure_api_version or "2024-10-21"
            )
        elif provider == "ollama":
            if "deepseek-r1" in model_config.model_name :
                log_info(logger, "initializing special provider for ollama deepseek-r1")
                return DeepSeekR1ChatOllama(
                    model=model_config.model_name,
                    temperature=model_config.temperature,
                    # num_ctx=32000,
                    base_url=os.getenv("OLLAMA_HOST")
                )
            else: 
                return ChatOllama(
                    model=model_config.model_name
                ) 
        else:
            raise ValueError(f"Unsupported provider: {provider}")
    except Exception as e:
        log_error(logger, "Error initializing LLM", {
            "provider": model_config.provider,
            "model": model_config.model_name,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error initializing LLM: {str(e)}")
    
class DeepSeekR1ChatOllama(ChatOllama):
    """Custom chat model for DeepSeek-R1."""

    def invoke(
        self,
        input: List[BaseMessage],
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Invoke the chat model with DeepSeek-R1 specific processing."""
        org_ai_message = super().invoke(input, config, **kwargs)
        org_content = org_ai_message.content

        # Extract reasoning content and main content
        org_content = str(org_ai_message.content)
        if "</think>" in org_content:
            parts = org_content.split("</think>")
            reasoning_content = parts[0].replace("<think>", "").strip()
            content = parts[1].strip()

            # Remove JSON Response tag if present
            if "**JSON Response:**" in content:
                content = content.split("**JSON Response:**")[-1].strip()

            # Create AIMessage with extra attributes
            message = AIMessage(content=content)
            setattr(message, "reasoning_content", reasoning_content)
            return message

        return AIMessage(content=org_ai_message.content)

    async def ainvoke(
        self,
        input: List[BaseMessage],
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Async invoke the chat model with DeepSeek-R1 specific processing."""
        org_ai_message = await super().ainvoke(input, config, **kwargs)
        org_content = org_ai_message.content

        # Extract reasoning content and main content
        org_content = str(org_ai_message.content)
        if "</think>" in org_content:
            parts = org_content.split("</think>")
            reasoning_content = parts[0].replace("<think>", "").strip()
            content = parts[1].strip()

            # Remove JSON Response tag if present
            if "**JSON Response:**" in content:
                content = content.split("**JSON Response:**")[-1].strip()

            # Create AIMessage with extra attributes
            message = AIMessage(content=content)
            setattr(message, "reasoning_content", reasoning_content)
            return message

        return AIMessage(content=org_ai_message.content)
