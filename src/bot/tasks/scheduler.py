"""
Планировщик фоновых задач
"""

import asyncio
import logging
from typing import List

from ..config import settings

logger = logging.getLogger(__name__)

# Список запущенных задач
background_tasks: List[asyncio.Task] = []


async def price_tracker():
    """Отслеживание цен"""
    from ..tasks.workers import check_prices
    
    while True:
        try:
            await check_prices()
            await asyncio.sleep(settings.PRICE_CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"Error in price_tracker: {e}", exc_info=True)
            await asyncio.sleep(5)  # Минимальная задержка при ошибке


async def new_gifts_tracker():
    """Отслеживание новых подарков"""
    from ..tasks.workers import check_new_gifts
    
    while True:
        try:
            await check_new_gifts()
            await asyncio.sleep(settings.NEW_GIFTS_CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"Error in new_gifts_tracker: {e}", exc_info=True)
            await asyncio.sleep(1)  # Минимальная задержка при ошибке


async def start_background_tasks():
    """Запуск всех фоновых задач"""
    logger.info("Starting background tasks...")
    
    # Запускаем задачи
    task1 = asyncio.create_task(price_tracker())
    task2 = asyncio.create_task(new_gifts_tracker())
    
    background_tasks.extend([task1, task2])
    
    logger.info(f"Started {len(background_tasks)} background tasks")


async def stop_background_tasks():
    """Остановка всех фоновых задач"""
    logger.info("Stopping background tasks...")
    
    for task in background_tasks:
        task.cancel()
    
    await asyncio.gather(*background_tasks, return_exceptions=True)
    
    background_tasks.clear()
    logger.info("Background tasks stopped")

