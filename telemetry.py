from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional, Any
from datetime import datetime
import asyncio
import psutil
import json
import logging
from database import get_db, Task
from logging_config import log_info, log_error
from browser import BrowserManager
from settings import TaskRequest
import aiohttp
import traceback
import os
# Logging configuration

from settings import METRICS_WEBHOOK_URL, ERROR_WEBHOOK_URL, NOTIFY_WEBHOOK_URL
logger = logging.getLogger('browser-use.telemetry')

async def send_metrics_to_webhook(metrics: Dict[str, Any]):
    """Send system metrics to webhook"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "metrics": metrics,
                "timestamp": datetime.utcnow().isoformat()
            }
            async with session.post(METRICS_WEBHOOK_URL, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to send metrics to webhook: {response.status}")
    except Exception as e:
        logger.error(f"Error sending metrics to webhook: {str(e)}")

async def send_error_to_webhook(error: str, context: str, task_id: Optional[str] = None):
    """Send error information to webhook"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "error": error,
                "context": context,
                "task_id": task_id,
                "timestamp": datetime.utcnow().isoformat(),
                "stack_trace": traceback.format_exc()
            }
            async with session.post(ERROR_WEBHOOK_URL, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to send error to webhook: {response.status}")
    except Exception as e:
        logger.error(f"Error sending to webhook: {str(e)}")

async def notify_new_run(task_id: int, task: str, config: Dict[str, Any]):
    """Notify webhook about a new task"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "task_id": task_id,
                "task": task,
                "config": config,
                "timestamp": datetime.utcnow().isoformat()
            }
            async with session.post(NOTIFY_WEBHOOK_URL, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to notify about new task: {response.status}")
    except Exception as e:
        logger.error(f"Error notifying about new task: {str(e)}")