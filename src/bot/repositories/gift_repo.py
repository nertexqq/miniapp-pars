"""
Репозиторий для работы с подарками
"""

from typing import Optional, List, Dict
from ..models.entities import Gift
from .base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class GiftRepository(BaseRepository):
    """Репозиторий подарков"""
    
    async def create(self, gift: Gift) -> int:
        """Создать подарок"""
        await self.execute("""
            INSERT INTO gifts (name, model, price, floor_price, photo_url, model_rarity, 
                             user_id, marketplace, model_floor_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            gift.name,
            gift.model,
            gift.price,
            gift.floor_price,
            gift.photo_url,
            gift.model_rarity,
            gift.user_id,
            gift.marketplace,
            gift.model_floor_price
        ))
        return await self.execute("SELECT LAST_INSERT_ID()", fetch=True)
    
    async def get_by_user(self, user_id: int, page: int = 0, per_page: int = 15) -> List[Dict]:
        """Получить подарки пользователя с пагинацией"""
        offset = page * per_page
        # В старой схеме нет id и created_at, поэтому просто без сортировки
        results = await self.fetch_all("""
            SELECT * FROM gifts WHERE user_id = %s
            LIMIT %s OFFSET %s
        """, (user_id, per_page, offset))
        return results
    
    async def get_unique_by_user(self, user_id: int, page: int = 0, per_page: int = 15) -> List[Dict]:
        """Получить уникальные подарки пользователя (по name и model)"""
        # Получаем все подарки пользователя
        all_gifts = await self.fetch_all(
            "SELECT * FROM gifts WHERE user_id = %s",
            (user_id,)
        )
        
        # Дедуплицируем по name и model
        seen = set()
        unique_gifts = []
        for gift in all_gifts:
            key = (gift.get('name'), gift.get('model'))
            if key not in seen:
                seen.add(key)
                unique_gifts.append(gift)
        
        # Пагинация
        offset = page * per_page
        return unique_gifts[offset:offset + per_page]
    
    async def delete(self, user_id: int, gift_name: str, model: Optional[str] = None) -> bool:
        """Удалить подарок"""
        if model:
            await self.execute("""
                DELETE FROM gifts 
                WHERE user_id = %s AND name = %s AND model = %s
            """, (user_id, gift_name, model))
        else:
            await self.execute("""
                DELETE FROM gifts 
                WHERE user_id = %s AND name = %s
            """, (user_id, gift_name))
        return True
    
    async def add(self, user_id: int, name: str, model: Optional[str] = None, marketplace: str = 'portals') -> bool:
        """Добавить подарок для пользователя"""
        # Если model None, используем пустую строку или 'N/A' в зависимости от схемы БД
        model_value = model if model is not None else ''
        # В старой схеме нет updated_at, поэтому просто игнорируем дубликаты
        try:
            await self.execute("""
                INSERT INTO gifts (name, model, user_id, marketplace, price, floor_price)
                VALUES (%s, %s, %s, %s, 0, 0)
            """, (name, model_value, user_id, marketplace))
        except Exception:
            # Подарок уже существует, игнорируем
            pass
        return True
    
    async def get_by_name_and_model(self, name: str, model: Optional[str], user_id: int) -> Optional[Gift]:
        """Получить подарок по имени и модели"""
        if model:
            result = await self.fetch_one("""
                SELECT * FROM gifts 
                WHERE name = %s AND model = %s AND user_id = %s
                LIMIT 1
            """, (name, model, user_id))
        else:
            result = await self.fetch_one("""
                SELECT * FROM gifts 
                WHERE name = %s AND user_id = %s
                LIMIT 1
            """, (name, user_id))
        
        if result:
            return Gift(**result)
        return None
    
    async def update_price(self, gift_id: int, price: float, floor_price: Optional[float] = None):
        """Обновить цену подарка"""
        if floor_price:
            await self.execute("""
                UPDATE gifts 
                SET price = %s, floor_price = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (price, floor_price, gift_id))
        else:
            await self.execute("""
                UPDATE gifts 
                SET price = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (price, gift_id))

