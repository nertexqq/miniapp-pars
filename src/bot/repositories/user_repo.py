"""
Репозиторий для работы с пользователями
"""

from typing import Optional, List
from ..models.entities import User
from .base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository):
    """Репозиторий пользователей"""
    
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Получить пользователя по ID"""
        result = await self.fetch_one(
            "SELECT * FROM bot_users WHERE user_id = %s",
            (user_id,)
        )
        if result:
            return User(**result)
        return None
    
    async def create_or_update(self, user: User) -> int:
        """Создать или обновить пользователя"""
        await self.execute("""
            INSERT INTO bot_users (user_id, username, first_name, last_name, notifications_enabled)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                username = VALUES(username),
                first_name = VALUES(first_name),
                last_name = VALUES(last_name),
                updated_at = CURRENT_TIMESTAMP
        """, (
            user.user_id,
            user.username,
            user.first_name,
            user.last_name,
            user.notifications_enabled
        ))
        return user.user_id
    
    async def get_all(self) -> List[User]:
        """Получить всех пользователей"""
        results = await self.fetch_all("SELECT * FROM bot_users")
        return [User(**r) for r in results]
    
    async def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь админом"""
        result = await self.fetch_one(
            "SELECT 1 FROM admins WHERE user_id = %s",
            (user_id,)
        )
        return result is not None
    
    async def is_allowed(self, user_id: int) -> bool:
        """Проверить, разрешен ли доступ пользователю"""
        # Проверяем админа
        if await self.is_admin(user_id):
            return True
        
        # Проверяем в списке разрешенных
        result = await self.fetch_one(
            "SELECT 1 FROM allowed_users WHERE user_id = %s",
            (user_id,)
        )
        return result is not None
    
    async def is_parsing_enabled(self, user_id: int) -> bool:
        """Проверить, включен ли парсинг для пользователя"""
        result = await self.fetch_one(
            "SELECT enabled FROM new_gifts_monitoring WHERE user_id = %s",
            (user_id,)
        )
        if result:
            return bool(result.get('enabled'))
        return False
    
    async def toggle_parsing(self, user_id: int, enabled: bool) -> bool:
        """Переключить парсинг для пользователя"""
        # Проверяем, есть ли колонка updated_at
        try:
            await self.execute("""
                INSERT INTO new_gifts_monitoring (user_id, enabled, enabled_at, last_check_at)
                VALUES (%s, %s, CASE WHEN %s = TRUE THEN CURRENT_TIMESTAMP ELSE NULL END, NULL)
                ON DUPLICATE KEY UPDATE
                    enabled = %s,
                    enabled_at = CASE WHEN %s = TRUE THEN COALESCE(enabled_at, CURRENT_TIMESTAMP) ELSE enabled_at END
            """, (user_id, enabled, enabled, enabled, enabled))
        except Exception as e:
            # Если ошибка с updated_at, пробуем без него
            if 'updated_at' in str(e):
                await self.execute("""
                    INSERT INTO new_gifts_monitoring (user_id, enabled, enabled_at, last_check_at)
                    VALUES (%s, %s, CASE WHEN %s = TRUE THEN CURRENT_TIMESTAMP ELSE NULL END, NULL)
                    ON DUPLICATE KEY UPDATE
                        enabled = %s,
                        enabled_at = CASE WHEN %s = TRUE THEN COALESCE(enabled_at, CURRENT_TIMESTAMP) ELSE enabled_at END
                """, (user_id, enabled, enabled, enabled, enabled))
            else:
                raise
        return True
    
    async def add_allowed_user(self, user_id: int, username: Optional[str] = None) -> bool:
        """Добавить пользователя в список разрешенных"""
        await self.execute("""
            INSERT INTO allowed_users (user_id, username)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE
                username = VALUES(username),
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, username))
        return True
    
    async def remove_allowed_user(self, user_id: int) -> bool:
        """Удалить пользователя из списка разрешенных"""
        await self.execute(
            "DELETE FROM allowed_users WHERE user_id = %s",
            (user_id,)
        )
        return True
    
    async def list_allowed_users(self) -> List[dict]:
        """Получить список всех разрешенных пользователей"""
        results = await self.fetch_all(
            "SELECT user_id, username FROM allowed_users ORDER BY user_id"
        )
        return results
    
    async def get_users_with_monitoring_enabled(self) -> List[dict]:
        """Получить список пользователей с включенным мониторингом"""
        results = await self.fetch_all(
            "SELECT user_id FROM new_gifts_monitoring WHERE enabled = TRUE"
        )
        return results

