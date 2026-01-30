"""
Конфигурация бота через переменные окружения
"""

import os
from typing import Optional
from pathlib import Path

# Пробуем импортировать pydantic_settings, если нет - используем pydantic
try:
    from pydantic_settings import BaseSettings
    HAS_PYDANTIC = True
except ImportError:
    try:
        from pydantic import BaseSettings
        HAS_PYDANTIC = True
    except ImportError:
        HAS_PYDANTIC = False
        # Fallback на простой класс если pydantic не установлен
        class BaseSettings:
            pass


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Telegram Bot
    BOT_TOKEN: str = ""
    API_ID: int = 0
    API_HASH: str = ""
    ADMIN_ID: int = 5299538981
    # URL Mini App (мониторинг подарков), например https://USER.github.io/portals_gifts_bot/
    MINIAPP_URL: Optional[str] = None
    
    # Database
    DB_HOST: str = "localhost"
    DB_USER: str = ""
    DB_PASS: str = ""
    DB_NAME: str = "portals_bot"
    DB_PORT: int = 3306
    
    # Marketplaces
    PORTALS_AUTH: Optional[str] = None
    TONNEL_AUTH: Optional[str] = None
    MRKT_AUTH: Optional[str] = None
    GETGEMS_API_KEY: Optional[str] = None
    PORTALS_API_URL: Optional[str] = None
    
    # Intervals
    CHECK_INTERVAL: int = 30  # Уменьшено до минимума
    NEW_GIFTS_CHECK_INTERVAL: int = 1  # Проверка каждую секунду
    PRICE_CHECK_INTERVAL: int = 10  # Уменьшено до минимума
    
    # Performance
    MAX_CONCURRENT_TASKS: int = 10  # Увеличено для параллельной обработки
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    
    # Cache
    CACHE_TTL: int = 300  # 5 minutes
    USE_REDIS: bool = False
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    if HAS_PYDANTIC:
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            case_sensitive = True


# Загружаем .env если есть
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Создаем глобальный экземпляр настроек
if HAS_PYDANTIC:
    try:
        settings = Settings()
    except Exception as e:
        # Если pydantic не может загрузить настройки, используем fallback
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to load settings with pydantic: {e}, using environment variables directly")
        HAS_PYDANTIC = False

if not HAS_PYDANTIC:
    # Fallback: загружаем напрямую из переменных окружения
    class SimpleSettings:
        BOT_TOKEN = os.getenv("BOT_TOKEN", "")
        API_ID = int(os.getenv("API_ID", "0"))
        API_HASH = os.getenv("API_HASH", "")
        ADMIN_ID = int(os.getenv("ADMIN_ID", "5299538981"))
        MINIAPP_URL = os.getenv("MINIAPP_URL")
        DB_HOST = os.getenv("DB_HOST", "localhost")
        DB_USER = os.getenv("DB_USER", "")
        DB_PASS = os.getenv("DB_PASS", "")
        DB_NAME = os.getenv("DB_NAME", "portals_bot")
        DB_PORT = int(os.getenv("DB_PORT", "3306"))
        PORTALS_AUTH = os.getenv("PORTALS_AUTH")
        TONNEL_AUTH = os.getenv("TONNEL_AUTH")
        MRKT_AUTH = os.getenv("MRKT_AUTH")
        GETGEMS_API_KEY = os.getenv("GETGEMS_API_KEY")
        PORTALS_API_URL = os.getenv("PORTALS_API_URL")
        CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))
        NEW_GIFTS_CHECK_INTERVAL = int(os.getenv("NEW_GIFTS_CHECK_INTERVAL", "1"))
        PRICE_CHECK_INTERVAL = int(os.getenv("PRICE_CHECK_INTERVAL", "10"))
        MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "3"))
        DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
        DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
        CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
        USE_REDIS = os.getenv("USE_REDIS", "false").lower() == "true"
        REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
        REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
        REDIS_DB = int(os.getenv("REDIS_DB", "0"))
        LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    settings = SimpleSettings()
