import os
import logging
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Body, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from pydantic import SecretStr
from api import router, collect_metrics_periodically
from database import engine, Base, get_db, init_db
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning

from browser_use import Agent, BrowserConfig, Browser

# Configuração de logging
logger = logging.getLogger('browser-use.server')

# Carregar variáveis de ambiente
load_dotenv()

# Configuração do banco de dados
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL não está definida nas variáveis de ambiente")

log_info(logger, f"Conectando ao banco de dados em: {DATABASE_URL}")

# Inicializar o banco de dados
init_db()

# Inicializa o aplicativo FastAPI
app = FastAPI(
    title="Browser-use API",
    description="API para controlar o Browser-use"
)

# Configura CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclui rotas da API
app.include_router(router)

# Modelos de dados
class BrowserConfigModel(BaseModel):
    headless: bool = True
    disable_security: bool = True
    extra_chromium_args: List[str] = []

class ModelConfig(BaseModel):
    provider: str = Field(..., description="Provedor do modelo: openai, azure")
    model_name: str = Field(..., description="Nome do modelo a ser utilizado")
    api_key: Optional[str] = Field(None, description="API key para o provedor (se necessário)")
    azure_endpoint: Optional[str] = Field(None, description="Endpoint para Azure OpenAI (se provider=azure)")
    azure_api_version: Optional[str] = Field(None, description="Versão da API do Azure OpenAI (se provider=azure)")
    temperature: float = Field(0.0, description="Temperatura para geração (0.0 a 1.0)")

class TaskRequest(BaseModel):
    task: str
    llm_config: ModelConfig
    browser_config: Optional[BrowserConfigModel] = None
    max_steps: int = 20
    use_vision: bool = True

class AgentResponse(BaseModel):
    task: str
    result: str
    success: bool
    steps_executed: int
    error: Optional[str] = None

# Função para obter o LLM com base na configuração
def get_llm(model_config: ModelConfig):
    try:
        provider = model_config.provider.lower()
        log_info(logger, "Inicializando LLM", {
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
                model='deepseek-chat',
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
        else:
            raise ValueError(f"Provedor não suportado: {provider}")
    except Exception as e:
        log_error(logger, "Erro ao inicializar LLM", {
            "provider": model_config.provider,
            "model": model_config.model_name,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao inicializar LLM: {str(e)}")

@app.post("/run", response_model=AgentResponse)
async def run_agent(
    request: TaskRequest = Body(...),
    db = Depends(get_db)
):
    log_info(logger, "Iniciando execução de agente", {
        "task": request.task,
        "provider": request.llm_config.provider,
        "model": request.llm_config.model_name
    })
    
    try:
        # Configurar o modelo LLM
        llm = get_llm(request.llm_config)
        
        # Configurar o navegador
        browser_config = BrowserConfig(
            headless=request.browser_config.headless if request.browser_config else True,
            disable_security=request.browser_config.disable_security if request.browser_config else True,
            extra_chromium_args=request.browser_config.extra_chromium_args if request.browser_config else []
        )
        
        log_debug(logger, "Configuração do navegador", {
            "headless": browser_config.headless,
            "disable_security": browser_config.disable_security
        })
        
        # Inicializar o navegador
        browser = Browser(config=browser_config)
        
        # Inicializar e executar o agente
        agent = Agent(
            task=request.task, 
            llm=llm, 
            browser=browser,
            use_vision=request.use_vision
        )
        
        result = await agent.run(max_steps=request.max_steps)
        
        # Extrair o resultado
        success = False
        content = "Tarefa não concluída"
        
        if result and result.history and len(result.history) > 0:
            last_item = result.history[-1]
            if last_item.result and len(last_item.result) > 0:
                last_result = last_item.result[-1]
                content = last_result.extracted_content or "Sem conteúdo extraído"
                success = last_result.is_done
        
        # Fechar o navegador após o uso
        await browser.close()
        
        return AgentResponse(
            task=request.task,
            result=content,
            success=success,
            steps_executed=len(result.history) if result and result.history else 0
        )
        
    except Exception as e:
        log_error(logger, "Erro durante execução do agente", {
            "task": request.task,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Endpoint para verificar a saúde da API"""
    log_debug(logger, "Verificando saúde da API")
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    
    # Obter porta do ambiente ou usar 8000 como padrão
    port = int(os.getenv("PORT", 8000))
    
    log_info(logger, "Iniciando servidor FastAPI", {
        "host": "0.0.0.0",
        "port": port
    })
    
    # Iniciar servidor
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info") 