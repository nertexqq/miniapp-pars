"""
Сервис кеширования (LRU + Redis)
"""

import asyncio
from typing import Optional, Any
from functools import wraps
import logging
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# LRU Cache для локального кеширования
class LRUCache:
    """Простой LRU кеш"""
    
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self.cache = {}
        self.access_order = []
    
    def get(self, key: str) -> Optional[Any]:
        """Получить значение из кеша"""
        if key in self.cache:
            # Обновляем порядок доступа
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]['value']
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Установить значение в кеш"""
        expire_at = None
        if ttl:
            expire_at = datetime.now() + timedelta(seconds=ttl)
        
        # Если ключ уже есть, обновляем
        if key in self.cache:
            self.cache[key] = {'value': value, 'expire_at': expire_at}
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)
            return
        
        # Если кеш полон, удаляем самый старый
        if len(self.cache) >= self.maxsize:
            oldest = self.access_order.pop(0)
            del self.cache[oldest]
        
        self.cache[key] = {'value': value, 'expire_at': expire_at}
        self.access_order.append(key)
    
    def delete(self, key: str):
        """Удалить ключ из кеша"""
        if key in self.cache:
            del self.cache[key]
            if key in self.access_order:
                self.access_order.remove(key)
    
    def clear(self):
        """Очистить кеш"""
        self.cache.clear()
        self.access_order.clear()
    
    def _clean_expired(self):
        """Очистить истекшие записи"""
        now = datetime.now()
        expired = []
        for key, data in self.cache.items():
            if data['expire_at'] and data['expire_at'] < now:
                expired.append(key)
        
        for key in expired:
            self.delete(key)


class CacheService:
    """Сервис кеширования с поддержкой Redis"""
    
    def __init__(self, use_redis: bool = False, redis_host: str = "localhost", 
                 redis_port: int = 6379, redis_db: int = 0, ttl: int = 300):
        self.use_redis = use_redis
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.ttl = ttl
        self.lru_cache = LRUCache(maxsize=512)
        self.redis_client = None
    
    async def init(self):
        """Инициализация Redis если нужно"""
        if self.use_redis:
            try:
                import redis.asyncio as redis
                self.redis_client = await redis.from_url(
                    f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}",
                    decode_responses=True
                )
                logger.info("Redis cache initialized")
            except ImportError:
                logger.warning("redis not installed, using LRU cache only")
                self.use_redis = False
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}, using LRU cache only")
                self.use_redis = False
    
    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кеша"""
        # Проверяем LRU кеш
        value = self.lru_cache.get(key)
        if value is not None:
            return value
        
        # Проверяем Redis
        if self.use_redis and self.redis_client:
            try:
                data = await self.redis_client.get(key)
                if data:
                    value = json.loads(data)
                    # Сохраняем в LRU для быстрого доступа
                    self.lru_cache.set(key, value, self.ttl)
                    return value
            except Exception as e:
                logger.error(f"Redis get error: {e}")
        
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Установить значение в кеш"""
        ttl = ttl or self.ttl
        
        # Сохраняем в LRU
        self.lru_cache.set(key, value, ttl)
        
        # Сохраняем в Redis
        if self.use_redis and self.redis_client:
            try:
                data = json.dumps(value)
                await self.redis_client.setex(key, ttl, data)
            except Exception as e:
                logger.error(f"Redis set error: {e}")
    
    async def delete(self, key: str):
        """Удалить ключ из кеша"""
        self.lru_cache.delete(key)
        
        if self.use_redis and self.redis_client:
            try:
                await self.redis_client.delete(key)
            except Exception as e:
                logger.error(f"Redis delete error: {e}")
    
    async def clear(self):
        """Очистить весь кеш"""
        self.lru_cache.clear()
        
        if self.use_redis and self.redis_client:
            try:
                await self.redis_client.flushdb()
            except Exception as e:
                logger.error(f"Redis clear error: {e}")
    
    async def close(self):
        """Закрыть соединения"""
        if self.redis_client:
            await self.redis_client.close()


def cached(ttl: int = 300, key_prefix: str = ""):
    """Декоратор для кеширования результатов функции"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Формируем ключ кеша
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Получаем сервис кеша из контекста (нужно передавать через DI)
            # Для упрощения используем глобальный экземпляр
            from ..di import container
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


