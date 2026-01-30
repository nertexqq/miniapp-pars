"""
Репозиторий для работы с настройками маркетплейсов
"""

from typing import List, Set, Dict
from ..models.entities import UserMarketplace
from .base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class MarketplaceRepository(BaseRepository):
    """Репозиторий настроек маркетплейсов"""
    
    async def get_enabled(self, user_id: int) -> Set[str]:
        """Получить включенные маркетплейсы пользователя"""
        results = await self.fetch_all("""
            SELECT marketplace FROM user_marketplaces 
            WHERE user_id = %s AND enabled = TRUE
        """, (user_id,))
        return {r['marketplace'] for r in results}
    
    async def toggle(self, user_id: int, marketplace: str, enabled: bool) -> bool:
        """Переключить маркетплейс"""
        await self.execute("""
            INSERT INTO user_marketplaces (user_id, marketplace, enabled)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE enabled = %s
        """, (user_id, marketplace, enabled, enabled))
        return True
    
    async def get_all_enabled_for_users(self, user_ids: List[int]) -> Dict[int, Set[str]]:
        """Получить включенные маркетплейсы для списка пользователей (батчинг)"""
        if not user_ids:
            return {}
        
        placeholders = ','.join(['%s'] * len(user_ids))
        results = await self.fetch_all(f"""
            SELECT user_id, marketplace FROM user_marketplaces 
            WHERE user_id IN ({placeholders}) AND enabled = TRUE
        """, tuple(user_ids))
        
        # Группируем по user_id
        user_marketplaces = {}
        for r in results:
            user_id = r['user_id']
            if user_id not in user_marketplaces:
                user_marketplaces[user_id] = set()
            user_marketplaces[user_id].add(r['marketplace'])
        
        return user_marketplaces

