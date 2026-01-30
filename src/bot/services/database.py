"""
Сервис для работы с базой данных
"""

import aiomysql
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseService:
    """Сервис для инициализации и управления БД"""
    
    def __init__(self, pool: aiomysql.Pool):
        self.pool = pool
    
    async def init_schema(self):
        """Инициализация схемы БД"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Создаем таблицы
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS bot_users (
                            user_id BIGINT PRIMARY KEY,
                            username VARCHAR(255),
                            first_name VARCHAR(255),
                            last_name VARCHAR(255),
                            notifications_enabled BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS gifts (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            model VARCHAR(255),
                            price DECIMAL(10, 2),
                            floor_price DECIMAL(10, 2),
                            model_floor_price DECIMAL(10, 2),
                            photo_url TEXT,
                            model_rarity VARCHAR(255),
                            user_id BIGINT NOT NULL,
                            marketplace VARCHAR(50) DEFAULT 'portals',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES bot_users(user_id) ON DELETE CASCADE,
                            INDEX idx_user_id (user_id),
                            INDEX idx_name_model (name, model)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_marketplaces (
                            user_id BIGINT NOT NULL,
                            marketplace VARCHAR(50) NOT NULL,
                            enabled BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, marketplace),
                            FOREIGN KEY (user_id) REFERENCES bot_users(user_id) ON DELETE CASCADE
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_price_filters (
                            user_id BIGINT NOT NULL,
                            gift_name VARCHAR(255) NOT NULL,
                            model VARCHAR(255),
                            min_price DECIMAL(10, 2),
                            max_price DECIMAL(10, 2),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, gift_name, model),
                            FOREIGN KEY (user_id) REFERENCES bot_users(user_id) ON DELETE CASCADE
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS admins (
                            user_id BIGINT PRIMARY KEY,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES bot_users(user_id) ON DELETE CASCADE
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS allowed_users (
                            user_id BIGINT PRIMARY KEY,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES bot_users(user_id) ON DELETE CASCADE
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS new_gifts_monitoring (
                            user_id BIGINT PRIMARY KEY,
                            enabled BOOLEAN DEFAULT FALSE,
                            enabled_at TIMESTAMP NULL,
                            last_check_at TIMESTAMP NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES bot_users(user_id) ON DELETE CASCADE
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    
                    await conn.commit()
                    logger.info("Database schema initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database schema: {e}", exc_info=True)
            raise


