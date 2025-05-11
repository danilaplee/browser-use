import os
import logging
from fastapi import FastAPI, HTTPException, Body, Depends
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from api import router
from database import get_db, init_db
from logging_config import log_info, log_error, log_debug, log_warning

from browser_use import Agent, BrowserConfig, Browser
from settings import get_llm, AgentResponse, TaskRequest

# Logging configuration
logger = logging.getLogger('browser-use.server')

# Load environment variables
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not defined in environment variables")

log_info(logger, f"Connecting to database at: {DATABASE_URL}")

# Initialize database
init_db()

# Initialize FastAPI application
app = FastAPI(
    title="Browser-use API",
    description="API to control Browser-use"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

@app.post("/run", response_model=AgentResponse)
async def run_agent(
    request: TaskRequest = Body(...),
    db = Depends(get_db)
):
    log_info(logger, "Starting agent execution", {
        "task": request.task,
        "provider": request.llm_config.provider,
        "model": request.llm_config.model_name
    })
    
    try:
        # Configure LLM model
        llm = get_llm(request.llm_config)
        
        # Configure browser
        browser_config = BrowserConfig(
            headless=request.browser_config.headless if request.browser_config else True,
            disable_security=request.browser_config.disable_security if request.browser_config else True,
            extra_chromium_args=request.browser_config.extra_chromium_args if request.browser_config else []
        )
        
        log_debug(logger, "Browser configuration", {
            "headless": browser_config.headless,
            "disable_security": browser_config.disable_security
        })
        
        # Initialize browser
        browser = Browser(config=browser_config)
        tool_calling_method = "auto"
        if "deepseek-r1" in request.llm_config.model_name:
            tool_calling_method = "json_mode"

        # Initialize and run agent
        agent = Agent(
            task=request.task, 
            llm=llm, 
            browser=browser,
            use_vision=request.use_vision,
            generate_gif=request.generate_gif,
            max_failures=request.max_failures,
            memory_interval=request.memory_interval,
            planner_interval=request.planner_interval,
            tool_calling_method=tool_calling_method
        )
        
        result = await agent.run(max_steps=request.max_steps)
        
        # Extract result
        success = False
        content = "Task not completed"
        videopath = agent.videopath
        if result and result.history and len(result.history) > 0:
            last_item = result.history[-1]
            if last_item.result and len(last_item.result) > 0:
                last_result = last_item.result[-1]
                content = last_result.extracted_content or "No content extracted"
                success = last_result.is_done
        
        # Close browser after use
        await browser.close()
        
        return AgentResponse(
            task=request.task,
            result=content,
            success=success,
            steps_executed=len(result.history) if result and result.history else 0,
            videopath=videopath
        )
        
    except Exception as e:
        log_error(logger, "Error during agent execution", {
            "task": request.task,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Endpoint to check API health"""
    log_debug(logger, "Checking API health")
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or use 8000 as default
    port = int(os.getenv("PORT", 8000))
    
    log_info(logger, "Starting FastAPI server", {
        "host": "0.0.0.0",
        "port": port
    })
    
    # Start server
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")