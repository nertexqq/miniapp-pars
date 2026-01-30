"""Миддлварь для rate limiting"""

import time
from typing import Callable, Dict, Any, Awaitable
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

# Хранилище времени последних запросов
user_last_request = defaultdict(float)
MIN_INTERVAL = 0.5  # Минимальный интервал между запросами (секунды)


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничение частоты запросов"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            current_time = time.time()
            last_time = user_last_request.get(user.id, 0)
            
            if current_time - last_time < MIN_INTERVAL:
                # Слишком частый запрос - пропускаем
                return
            
            user_last_request[user.id] = current_time
        
        return await handler(event, data)


