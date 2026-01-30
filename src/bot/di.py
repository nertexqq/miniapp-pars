"""
Dependency Injection контейнер
"""

from typing import Optional
import aiomysql
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .config import settings
from .services.database import DatabaseService
from .services.cache import CacheService
from .services.parser import ParserService


class Container:
    """DI контейнер для зависимостей"""
    
    def __init__(self):
        self._bot: Optional[Bot] = None
        self._dp: Optional[Dispatcher] = None
        self._db_pool: Optional[aiomysql.Pool] = None
        self._db_service: Optional[DatabaseService] = None
        self._cache_service: Optional[CacheService] = None
        self._parser_service: Optional[ParserService] = None
    
    async def init_bot(self) -> Bot:
        """Инициализация бота"""
        if self._bot is None:
            self._bot = Bot(token=settings.BOT_TOKEN)
        return self._bot
    
    async def init_dispatcher(self) -> Dispatcher:
        """Инициализация диспетчера"""
        if self._dp is None:
            storage = MemoryStorage()
            self._dp = Dispatcher(storage=storage)
        return self._dp
    
    async def init_db_pool(self) -> aiomysql.Pool:
        """Инициализация пула соединений БД"""
        if self._db_pool is None:
            self._db_pool = await aiomysql.create_pool(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASS,
                db=settings.DB_NAME,
                minsize=1,
                maxsize=settings.DB_POOL_SIZE,
                autocommit=False
            )
        return self._db_pool
    
    async def get_db_service(self) -> DatabaseService:
        """Получить сервис БД"""
        if self._db_service is None:
            pool = await self.init_db_pool()
            self._db_service = DatabaseService(pool)
        return self._db_service
    
    async def get_cache_service(self) -> CacheService:
        """Получить сервис кеширования"""
        if self._cache_service is None:
            self._cache_service = CacheService(
                use_redis=settings.USE_REDIS,
                redis_host=settings.REDIS_HOST,
                redis_port=settings.REDIS_PORT,
                redis_db=settings.REDIS_DB,
                ttl=settings.CACHE_TTL
            )
            await self._cache_service.init()
        return self._cache_service
    
    async def get_parser_service(self) -> ParserService:
        """Получить сервис парсинга"""
        if self._parser_service is None:
            cache = await self.get_cache_service()
            self._parser_service = ParserService(cache)
        return self._parser_service
    
    async def shutdown(self):
        """Закрытие всех соединений"""
        if self._db_pool:
            self._db_pool.close()
            await self._db_pool.wait_closed()
        
        if self._cache_service:
            await self._cache_service.close()
        
        if self._bot:
            await self._bot.session.close()


# Глобальный контейнер
container = Container()


