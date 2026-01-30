"""
Конфигурация для Telegram-бота мониторинга подарков Portals
"""

import os
from typing import Optional
from pathlib import Path

# Загружаем переменные окружения из .env файла, если он существует
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv не установлен, используем только системные переменные окружения
    pass

# Telegram Bot Token (получить у @BotFather)
BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN") or "7179113440:AAESqYNY3-c-SJ1XuomopfNODkLQRD20qUg"

# Telegram API credentials (для работы с Portals API)
API_ID: int = int(os.getenv("API_ID", "33432004"))
API_HASH: Optional[str] = os.getenv("API_HASH") or "ceb4716304ce30d4d5570304a2352057"

# MySQL Database credentials
DB_HOST: Optional[str] = os.getenv("DB_HOST", "localhost")
DB_USER: Optional[str] = os.getenv("DB_USER", "zxczxczxc")
DB_PASS: Optional[str] = os.getenv("DB_PASS", "zxczxczxc")
DB_NAME: Optional[str] = os.getenv("DB_NAME", "portals_bot")

# Интервал проверки цен (в секундах)
CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "60"))  # По умолчанию 1 минута

# URL API Portals (можно переопределить через переменную окружения)
PORTALS_API_URL: Optional[str] = os.getenv("PORTALS_API_URL")

# Tonnel Marketplace Auth Token
TONNEL_AUTH: Optional[str] = os.getenv("TONNEL_AUTH")

# MRKT Marketplace Auth Token
MRKT_AUTH: Optional[str] = os.getenv("MRKT_AUTH", "09661eb0-c776-4391-a01e-990306cceca2")

# Portals Auth Token (можно переопределить через переменную окружения)
PORTALS_AUTH: Optional[str] = os.getenv("PORTALS_AUTH", "tma query_id=AAEljOA7AgAAACWM4DtP1j_n&user=%7B%22id%22%3A5299538981%2C%22first_name%22%3A%22%D0%BD%D0%B5%D1%83%D0%BA%D0%BB%D1%8E%D0%B6%D0%B8%D0%B9%20%D0%BF%D0%B0%D1%80%D0%B5%D0%BD%D1%8C%22%2C%22last_name%22%3A%22%22%2C%22username%22%3A%22unreaIised%22%2C%22language_code%22%3A%22ru%22%2C%22allows_write_to_pm%22%3Atrue%2C%22photo_url%22%3A%22https%3A%5C%2F%5C%2Ft.me%5C%2Fi%5C%2Fuserpic%5C%2F320%5C%2Fx8kLICshxW6DfqhASMsMKDW6pm1lQjrR9hus0CYr2LHxJcncpUIvQ0ZklI8YpK-F.svg%22%7D&auth_date=1768643043&signature=RFNqlz-oUNjxZo-WCke5B5W1_RhjcPUXFLX9_TUA1kBYUJO1TtCKGKRKT1WuGeIdeGQ4__EJGqoEUnrXrCjAAw&hash=6c02d9f02160a6d8080d511518483e974bace791bc6af6c2b3eb03dd0c0b4f20")

# GetGems API Key (optional; getgems_wrapper uses default if not set)
GETGEMS_API_KEY: Optional[str] = os.getenv("GETGEMS_API_KEY", "1769627125531-mainnet-10291171-r-rXYOhAEbyTSLjB55S9K85A9EocY8ZorABB49j1JXgLhOS9Ek")

