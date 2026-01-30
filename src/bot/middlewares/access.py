"""
Миддлварь для проверки доступа пользователей
"""

import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from ..di import container
from ..repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)


class AccessControlMiddleware(BaseMiddleware):
    """Проверка доступа пользователя - только разрешенные пользователи могут использовать бота"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        
        if not user:
            return await handler(event, data)
        
        # Проверяем доступ
        pool = await container.init_db_pool()
        user_repo = UserRepository(pool)
        
        is_allowed = await user_repo.is_allowed(user.id)
        
        if not is_allowed:
            # Пользователь не имеет доступа
            error_message = (
                "❌ У вас нет доступа к этому боту.\n\n"
                "Обратитесь к администратору для получения доступа."
            )
            
            try:
                if isinstance(event, (Message, CallbackQuery)):
                    if isinstance(event, CallbackQuery):
                        await event.answer(error_message, show_alert=True)
                    else:
                        await event.answer(error_message)
            except TelegramBadRequest:
                # Игнорируем ошибки отправки
                pass
            except Exception as e:
                logger.error(f"Error sending access denied message: {e}")
            
            # Не вызываем handler - блокируем запрос
            return
        
        # Пользователь имеет доступ - продолжаем
        return await handler(event, data)


