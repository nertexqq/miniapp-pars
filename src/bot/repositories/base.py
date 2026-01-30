"""
Базовый репозиторий с общими методами
"""

from typing import Optional, List, Dict, Any
import aiomysql
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseRepository(ABC):
    """Базовый класс для репозиториев"""
    
    def __init__(self, pool: aiomysql.Pool):
        self.pool = pool
    
    async def execute(self, query: str, params: Optional[tuple] = None, fetch: bool = False):
        """Выполнить запрос"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(query, params)
                    if fetch:
                        return await cur.fetchall()
                    await conn.commit()
                    return cur.lastrowid
        except Exception as e:
            logger.error(f"Database error in {self.__class__.__name__}: {e}", exc_info=True)
            raise
    
    async def fetch_one(self, query: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        """Получить одну запись"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(query, params)
                    return await cur.fetchone()
        except Exception as e:
            logger.error(f"Database error in {self.__class__.__name__}: {e}", exc_info=True)
            raise
    
    async def fetch_all(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Получить все записи"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(query, params)
                    return await cur.fetchall()
        except Exception as e:
            logger.error(f"Database error in {self.__class__.__name__}: {e}", exc_info=True)
            raise


