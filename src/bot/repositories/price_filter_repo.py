"""
Репозиторий для работы с фильтрами цен
"""

from typing import Optional, List
from ..models.entities import PriceFilter
from .base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class PriceFilterRepository(BaseRepository):
    """Репозиторий фильтров цен"""
    
    async def create_or_update(self, price_filter: PriceFilter) -> int:
        """Создать или обновить фильтр цены"""
        await self.execute("""
            INSERT INTO user_price_filters (user_id, gift_name, model, min_price, max_price)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                min_price = VALUES(min_price),
                max_price = VALUES(max_price),
                updated_at = CURRENT_TIMESTAMP
        """, (
            price_filter.user_id,
            price_filter.gift_name,
            price_filter.model,
            price_filter.min_price,
            price_filter.max_price
        ))
        return price_filter.user_id
    
    async def get_by_gift(self, user_id: int, gift_name: str, model: Optional[str] = None) -> Optional[dict]:
        """Получить фильтр для подарка"""
        # Сначала пробуем старую схему (только user_id) - она более распространена
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    # Пробуем запрос только по user_id (старая схема)
                    await cur.execute("""
                        SELECT * FROM user_price_filters 
                        WHERE user_id = %s
                    """, (user_id,))
                    result = await cur.fetchone()
                    if result:
                        return result
                    
                    # Если нет результата, пробуем новую схему (с gift_name)
                    try:
                        if model:
                            await cur.execute("""
                                SELECT * FROM user_price_filters 
                                WHERE user_id = %s AND gift_name = %s AND model = %s
                            """, (user_id, gift_name, model))
                        else:
                            await cur.execute("""
                                SELECT * FROM user_price_filters 
                                WHERE user_id = %s AND gift_name = %s AND model IS NULL
                            """, (user_id, gift_name))
                        return await cur.fetchone()
                    except Exception:
                        # Новая схема не поддерживается, возвращаем None
                        return None
        except Exception as e:
            # Если ошибка при запросе, возвращаем None (нет фильтра)
            logger.debug(f"Error getting price filter for user {user_id}: {e}")
            return None
    
    async def should_process(self, user_id: int, gift_name: str, model: Optional[str], price: float) -> bool:
        """Проверить, должен ли подарок быть обработан с учетом фильтра"""
        try:
            filter_obj = await self.get_by_gift(user_id, gift_name, model)
            
            if not filter_obj:
                return True  # Нет фильтра - обрабатываем
            
            min_price = filter_obj.get('min_price') if isinstance(filter_obj, dict) else getattr(filter_obj, 'min_price', None)
            max_price = filter_obj.get('max_price') if isinstance(filter_obj, dict) else getattr(filter_obj, 'max_price', None)
            
            if min_price is not None and price < float(min_price):
                return False
            
            if max_price is not None and price > float(max_price):
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error in should_process for user {user_id}, gift {gift_name}, model {model}: {e}", exc_info=True)
            # При ошибке обрабатываем подарок (не фильтруем)
            return True

