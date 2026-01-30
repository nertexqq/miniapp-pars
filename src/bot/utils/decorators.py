"""Декораторы"""

from functools import wraps
from typing import Callable, Any, Awaitable
from ..di import container


def cached(ttl: int = 300, key_prefix: str = ""):
    """Декоратор для кеширования результатов функции"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Формируем ключ кеша
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Получаем сервис кеша
            cache_service = await container.get_cache_service()
            
            # Пытаемся получить из кеша
            cached_value = await cache_service.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Выполняем функцию
            result = await func(*args, **kwargs)
            
            # Сохраняем в кеш
            await cache_service.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


