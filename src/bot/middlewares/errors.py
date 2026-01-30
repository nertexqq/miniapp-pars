"""Миддлварь для обработки ошибок"""

import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, ErrorEvent

logger = logging.getLogger(__name__)


class ErrorMiddleware(BaseMiddleware):
    """Обработка ошибок"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"Error in handler: {e}", exc_info=True)
            
            # Пытаемся отправить сообщение об ошибке пользователю
            if hasattr(event, 'answer'):
                try:
                    await event.answer("❌ Произошла ошибка. Попробуйте позже.")
                except:
                    pass
            
            raise


