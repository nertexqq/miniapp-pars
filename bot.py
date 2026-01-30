
"""
Основной модуль Telegram-бота для мониторинга подарков Portals и Tonnel
"""

import asyncio
import inspect
import re
import aiomysql
from asyncio import Semaphore
from typing import Optional, List, Dict, Any, Tuple
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
# Используем асинхронную библиотеку aportalsmp (лучше подходит для aiogram)
try:
    from aportalsmp import update_auth, search, filterFloors
    # Пробуем импортировать функции для продаж, если они есть
    try:
        from aportalsmp import get_sales_history, search_by_id
        # Пробуем импортировать функции для флора и продаж модели
        try:
            from aportalsmp import get_model_floor_price, get_gift_floor_price, get_model_sales_history
        except ImportError:
            # Если нет, используем локальные версии
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from portalsmp import get_model_floor_price, get_gift_floor_price, get_model_sales_history
    except ImportError:
        # Если нет, используем локальные версии
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from portalsmp import get_sales_history, search_by_id, get_model_floor_price, get_gift_floor_price, get_model_sales_history
except ImportError:
    # Если aportalsmp не установлен, пробуем синхронную версию portalsmp
    try:
        from portalsmp import (
            update_auth, search, filterFloors, get_sales_history, search_by_id,
            get_model_floor_price, get_gift_floor_price, get_model_sales_history
        )
    except ImportError:
        # Если библиотека не установлена, используем локальный модуль
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from portalsmp import (
            update_auth, search, filterFloors, get_sales_history, search_by_id,
            get_model_floor_price, get_gift_floor_price, get_model_sales_history
        )
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Импортируем обертку для Tonnel
try:
    from tonnelmp_wrapper import (
        search_tonnel, get_tonnel_model_floor_price, get_tonnel_gift_floor_price,
        get_tonnel_model_sales_history, get_tonnel_gift_by_id, get_tonnel_gift_sales_history
    )
except ImportError:
    logger.warning("tonnelmp_wrapper not available")
    search_tonnel = None
    get_tonnel_model_floor_price = None
    get_tonnel_gift_floor_price = None
    get_tonnel_model_sales_history = None
    get_tonnel_gift_by_id = None
    get_tonnel_gift_sales_history = None

# Импортируем обертку для MRKT
try:
    from mrktmp_wrapper import (
        search_mrkt, get_mrkt_model_floor_price, get_mrkt_gift_floor_price,
        get_mrkt_model_sales_history, get_mrkt_gift_by_id, get_mrkt_auth_token
    )
except ImportError:
    logger.warning("mrktmp_wrapper not available")
    search_mrkt = None
    get_mrkt_model_floor_price = None
    get_mrkt_gift_floor_price = None
    get_mrkt_model_sales_history = None
    get_mrkt_gift_by_id = None
    get_mrkt_auth_token = None

# GetGems удален

from config import (
    PORTALS_AUTH,
    BOT_TOKEN, API_ID, API_HASH,
    DB_HOST, DB_USER, DB_PASS, DB_NAME, TONNEL_AUTH, MRKT_AUTH
)
# Снижаем уровень спама от portalsmp (sales history warnings)
logging.getLogger("portalsmp").setLevel(logging.ERROR)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

auth_token = None
db_pool = None
ADMIN_ID = 5299538981  # ID админа

# Глобальная переменная для отслеживания новых подарков
new_gifts_monitoring_enabled = {}  # user_id -> bool
new_gifts_last_ids = {}  # marketplace -> set of gift_ids
# Семафор для ограничения параллельных задач обработки новых подарков (максимум 10 одновременно для быстрой обработки всех новых подарков)
processing_semaphore = Semaphore(10)


class AddGift(StatesGroup):
    waiting_name = State()
    waiting_model = State()
    waiting_price_filter = State()

class GetModels(StatesGroup):
    waiting_name = State()

class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_remove_user_id = State()

class GiftSelection(StatesGroup):
    browsing_gifts = State()
    searching_gifts = State()
    browsing_models = State()
    searching_models = State()
    entering_price_filter = State()


async def init_db():
    """Инициализация базы данных MySQL"""
    global db_pool
    try:
        # Сначала пытаемся подключиться без указания базы данных для её создания
        try:
            conn = await aiomysql.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASS,
                db=None
            )
            async with conn.cursor() as cur:
                await cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS {DB_NAME} "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
                await conn.commit()
            conn.close()
            logger.info(f"Database '{DB_NAME}' created or already exists")
        except Exception as e:
            logger.warning(f"Could not create database (might already exist): {e}")
        
        # Подключаемся к базе данных
        db_pool = await aiomysql.create_pool(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
            minsize=1,
            maxsize=10
        )
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS gifts (
                    name VARCHAR(255) NOT NULL,
                    model VARCHAR(255),
                    price FLOAT DEFAULT 0,
                    floor_price FLOAT DEFAULT 0,
                    photo_url TEXT,
                    model_rarity VARCHAR(50),
                    user_id BIGINT NOT NULL,
                    marketplace VARCHAR(50) DEFAULT 'portals',
                    PRIMARY KEY (user_id, name(255), model(255), marketplace(50))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Миграция: добавляем колонку marketplace если её нет
                try:
                    await cur.execute("""
                        ALTER TABLE gifts 
                        ADD COLUMN marketplace VARCHAR(50) DEFAULT 'portals'
                    """)
                    logger.info("Added marketplace column to gifts table")
                except Exception as e:
                    if "Duplicate column name" not in str(e):
                        logger.warning(f"Could not add marketplace column: {e}")
                
                # Миграция: добавляем колонку model_floor_price если её нет
                try:
                    await cur.execute("""
                        ALTER TABLE gifts 
                        ADD COLUMN model_floor_price FLOAT DEFAULT NULL
                    """)
                    logger.info("Added model_floor_price column to gifts table")
                except Exception as e:
                    if "Duplicate column name" not in str(e):
                        logger.warning(f"Could not add model_floor_price column: {e}")
                
                # Таблица для отслеживания уже уведомленных подарков
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS notified_gifts (
                    gift_id VARCHAR(255) NOT NULL PRIMARY KEY,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_notified_at (notified_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Таблица для хранения всех пользователей бота (для отправки уведомлений)
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_users (
                    user_id BIGINT NOT NULL PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    notifications_enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Таблица для админов
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT NOT NULL PRIMARY KEY,
                    username VARCHAR(255),
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_id (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Таблица для разрешенных пользователей
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS allowed_users (
                    user_id BIGINT NOT NULL PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    added_by BIGINT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_id (user_id),
                    INDEX idx_added_by (added_by)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Таблица для отслеживания включенного мониторинга новых подарков
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS new_gifts_monitoring (
                    user_id BIGINT NOT NULL PRIMARY KEY,
                    enabled BOOLEAN DEFAULT FALSE,
                    enabled_at TIMESTAMP NULL,
                    last_check_at TIMESTAMP NULL,
                    INDEX idx_enabled (enabled)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Таблица для настроек маркетплейсов пользователя
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS user_marketplaces (
                    user_id BIGINT NOT NULL,
                    marketplace VARCHAR(50) NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    PRIMARY KEY (user_id, marketplace),
                    INDEX idx_user_id (user_id),
                    INDEX idx_marketplace (marketplace)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Таблица для фильтров цены пользователя
                await cur.execute("""
                CREATE TABLE IF NOT EXISTS user_price_filters (
                    user_id BIGINT NOT NULL PRIMARY KEY,
                    min_price FLOAT DEFAULT NULL,
                    max_price FLOAT DEFAULT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_user_id (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Инициализируем настройки по умолчанию для всех пользователей (все маркетплейсы включены)
                # Это делается при первом использовании, не здесь
                
                # Добавляем первого админа (5299538981)
                try:
                    await cur.execute("""
                        INSERT IGNORE INTO admins (user_id, username)
                        VALUES (%s, %s)
                    """, (5299538981, 'stillontop'))
                    await conn.commit()
                    logger.info("Added default admin to database")
                except Exception as e:
                    logger.warning(f"Could not add default admin: {e}")
                
                # Миграция: добавляем колонку notifications_enabled если её нет
                try:
                    await cur.execute("""
                        ALTER TABLE bot_users 
                        ADD COLUMN notifications_enabled BOOLEAN DEFAULT TRUE
                    """)
                    logger.info("Added notifications_enabled column to bot_users table")
                except Exception as e:
                    # Колонка уже существует или другая ошибка
                    if "Duplicate column name" not in str(e):
                        logger.warning(f"Could not add notifications_enabled column: {e}")
                
                # Миграция: добавляем колонку marketplace если её нет
                try:
                    await cur.execute("""
                        ALTER TABLE bot_users 
                        ADD COLUMN marketplace VARCHAR(50) DEFAULT 'portals'
                    """)
                    logger.info("Added marketplace column to bot_users table")
                except Exception as e:
                    # Колонка уже существует или другая ошибка
                    if "Duplicate column name" not in str(e):
                        logger.warning(f"Could not add marketplace column: {e}")
                
                await conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to initialize database: {error_msg}")
        
        if "Can't connect to MySQL server" in error_msg or "2003" in error_msg:
            logger.error("=" * 60)
            logger.error("MySQL SERVER IS NOT RUNNING!")
            logger.error("Please start MySQL server and try again.")
            logger.error("=" * 60)
            print("\n" + "=" * 60)
            print("ОШИБКА: MySQL сервер не запущен!")
            print("Пожалуйста, запустите MySQL сервер и попробуйте снова.")
            print("=" * 60 + "\n")
        else:
            logger.error("Please check MySQL credentials in .env file")
        
        raise


async def init_auth():
    """Инициализация аутентификации в Portals API"""
    global auth_token
    import os
    import sqlite3
    
    # Пытаемся аутентифицироваться
    try:
        auth_token = await update_auth(API_ID, API_HASH)
        if auth_token:
            logger.info("Authentication successful")
        else:
            logger.error("Authentication failed")
        return auth_token
    except (sqlite3.OperationalError, Exception) as e:
        # Если ошибка связана с устаревшей схемой SQLite сессии Pyrogram
        if "no column named username" in str(e) or "table peers" in str(e).lower():
            logger.warning("Detected corrupted Pyrogram session. Removing old session files...")
            # Удаляем старые файлы сессий
            session_files = ["account.session", "account.session-journal"]
            for session_file in session_files:
                if os.path.exists(session_file):
                    try:
                        os.remove(session_file)
                        logger.info(f"Removed {session_file}")
                    except Exception as rm_e:
                        logger.error(f"Failed to remove {session_file}: {rm_e}")
            
            logger.info("Please restart the bot. The session will be recreated with the correct schema.")
            logger.error(f"Session error: {e}")
            raise
        else:
            # Другие ошибки просто пробрасываем дальше
            logger.error(f"Authentication error: {e}")
            raise


async def init_mrkt_auth():
    """Инициализация аутентификации в MRKT API - используем токен из конфига"""
    return MRKT_AUTH


async def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    if user_id == ADMIN_ID:
        return True
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM admins WHERE user_id = %s", (user_id,))
                result = await cur.fetchone()
                return result is not None
    except Exception as e:
        logger.error(f"Error checking admin: {e}")
        return False

async def is_allowed_user(user_id: int) -> bool:
    """Проверка, разрешен ли пользователю доступ к функциям бота"""
    if await is_admin(user_id):
        return True
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM allowed_users WHERE user_id = %s", (user_id,))
                result = await cur.fetchone()
                return result is not None
    except Exception as e:
        logger.error(f"Error checking allowed user: {e}")
        return False

async def add_gift_to_db(gift, user_id, model, marketplace='portals', model_floor_price=None):
    """Добавление подарка в базу данных"""
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("""
                REPLACE INTO gifts (name, model, price, floor_price, photo_url, model_rarity, user_id, marketplace, model_floor_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    gift.get("name"),
                    model,
                    gift.get("price"),
                    gift.get("floor_price"),
                    gift.get("photo_url"),
                    gift.get("model_rarity"),
                    user_id,
                    marketplace,
                    model_floor_price
                ))
            except Exception as e:
                # Если колонка model_floor_price не существует, обновляем без неё
                logger.warning(f"Column model_floor_price might not exist: {e}")
                await cur.execute("""
                REPLACE INTO gifts (name, model, price, floor_price, photo_url, model_rarity, user_id, marketplace)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    gift.get("name"),
                    model,
                    gift.get("price"),
                    gift.get("floor_price"),
                    gift.get("photo_url"),
                    gift.get("model_rarity"),
                    user_id,
                    marketplace
                ))
            await conn.commit()


@dp.callback_query(lambda c: c.data == "menu_main")
async def callback_menu_main(callback: types.CallbackQuery):
    """Обработка возврата в главное меню"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Главное меню с кнопками
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить подарок", callback_data="menu_add"),
            InlineKeyboardButton(text="📋 Список подарков", callback_data="menu_list")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")
        ],
        [
            InlineKeyboardButton(text="🔍 Функции", callback_data="menu_functions")
        ]
    ])
    
    # Добавляем кнопку админ-панели для админов
    if await is_admin(callback.from_user.id):
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="👑 Админ-панель", callback_data="menu_admin")
        ])
    
    text = (
        "🤖 Бот мониторинга подарков\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    # Сохраняем пользователя в базу данных БЕЗ автоматического включения мониторинга
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Добавляем пользователя БЕЗ включения мониторинга (мониторинг включается только через кнопку)
                    try:
                        await cur.execute("""
                            INSERT INTO bot_users (user_id, username, first_name, last_name, notifications_enabled)
                            VALUES (%s, %s, %s, %s, FALSE)
                            ON DUPLICATE KEY UPDATE
                                username = VALUES(username),
                                first_name = VALUES(first_name),
                                last_name = VALUES(last_name)
                        """, (
                            message.from_user.id,
                            message.from_user.username,
                            message.from_user.first_name,
                            message.from_user.last_name
                        ))
                        # Убеждаемся, что мониторинг новых подарков выключен
                        await cur.execute("""
                            INSERT INTO new_gifts_monitoring (user_id, enabled, enabled_at, last_check_at)
                            VALUES (%s, FALSE, NULL, NULL)
                            ON DUPLICATE KEY UPDATE
                                enabled = FALSE,
                                updated_at = CURRENT_TIMESTAMP
                        """, (message.from_user.id,))
                        
                        # Убеждаемся, что все маркетплейсы выключены при первом запуске
                        # Проверяем, есть ли уже настройки
                        await cur.execute("""
                            SELECT COUNT(*) FROM user_marketplaces WHERE user_id = %s
                        """, (message.from_user.id,))
                        result = await cur.fetchone()
                        if result and result[0] == 0:
                            # Если настроек нет, создаем их с выключенными маркетплейсами
                            await cur.execute("""
                                INSERT INTO user_marketplaces (user_id, marketplace, enabled)
                                VALUES (%s, 'portals', FALSE),
                                       (%s, 'tonnel', FALSE),
                                       (%s, 'mrkt', FALSE)
                            """, (message.from_user.id, message.from_user.id, message.from_user.id))
                    except Exception as e:
                        # Если колонка не существует, добавляем без неё
                        logger.warning(f"Column notifications_enabled might not exist: {e}")
                        await cur.execute("""
                            INSERT INTO bot_users (user_id, username, first_name, last_name)
                            VALUES (%s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                username = VALUES(username),
                                first_name = VALUES(first_name),
                                last_name = VALUES(last_name)
                        """, (
                            message.from_user.id,
                            message.from_user.username,
                            message.from_user.first_name,
                            message.from_user.last_name
                        ))
                    await conn.commit()
                    logger.info(f"User {message.from_user.id} added/updated in bot_users (monitoring disabled by default)")
        except Exception as e:
            logger.error(f"Error saving user: {e}")
    
    # Проверяем доступ
    if not await is_allowed_user(message.from_user.id):
        await message.answer(
            "❌ У вас нет доступа к боту.\n\n"
            "Обратитесь к администратору для получения доступа."
        )
        return
    
    # Главное меню с кнопками
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить подарок", callback_data="menu_add"),
            InlineKeyboardButton(text="📋 Список подарков", callback_data="menu_list")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")
        ],
        [
            InlineKeyboardButton(text="🔍 Функции", callback_data="menu_functions")
        ]
    ])
    
    # Добавляем кнопку админ-панели для админов
    if await is_admin(message.from_user.id):
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="👑 Админ-панель", callback_data="menu_admin")
        ])
    
    await message.answer(
        "🤖 Бот мониторинга подарков\n\n"
        "Выберите действие:",
        reply_markup=keyboard
    )




@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    """Настройки - выбор маркетплейсов (можно выбрать несколько)"""
    if not db_pool:
        await message.answer("❌ База данных не подключена.")
        return
    
    try:
        # Получаем включенные маркетплейсы пользователя
        enabled_marketplaces = set()
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT marketplace FROM user_marketplaces 
                    WHERE user_id = %s AND enabled = TRUE
                """, (message.from_user.id,))
                results = await cur.fetchall()
                for (mp,) in results:
                    enabled_marketplaces.add(mp)
        
        # Создаем клавиатуру для выбора маркетплейсов (чекбоксы) — без GetGems
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Portals" if 'portals' in enabled_marketplaces else "☐ Portals",
                    callback_data="toggle_marketplace_portals"
                ),
                InlineKeyboardButton(
                    text="✅ Tonnel" if 'tonnel' in enabled_marketplaces else "☐ Tonnel",
                    callback_data="toggle_marketplace_tonnel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ MRKT" if 'mrkt' in enabled_marketplaces else "☐ MRKT",
                    callback_data="toggle_marketplace_mrkt"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")
            ]
        ])
        
        enabled_list = ', '.join(sorted(enabled_marketplaces))
        
        await message.answer(
            f"⚙️ <b>Настройки маркетплейсов</b>\n\n"
            f"Включенные маркетплейсы: <b>{enabled_list}</b>\n\n"
            f"Нажмите на маркетплейс, чтобы включить/выключить:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in settings: {e}", exc_info=True)
        await message.answer("❌ Ошибка при получении настроек.")


@dp.callback_query(lambda c: c.data == "menu_settings")
async def callback_menu_settings(callback: types.CallbackQuery):
    """Обработка открытия меню настроек"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    if not db_pool:
        await callback.answer("❌ База данных не подключена", show_alert=True)
        return
    
    try:
        # Получаем включенные маркетплейсы пользователя
        enabled_marketplaces = set()
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT marketplace FROM user_marketplaces 
                    WHERE user_id = %s AND enabled = TRUE
                """, (callback.from_user.id,))
                results = await cur.fetchall()
                for (mp,) in results:
                    enabled_marketplaces.add(mp)
        
        # Создаем клавиатуру для выбора маркетплейсов (чекбоксы) — без GetGems
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Portals" if 'portals' in enabled_marketplaces else "☐ Portals",
                    callback_data="toggle_marketplace_portals"
                ),
                InlineKeyboardButton(
                    text="✅ Tonnel" if 'tonnel' in enabled_marketplaces else "☐ Tonnel",
                    callback_data="toggle_marketplace_tonnel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ MRKT" if 'mrkt' in enabled_marketplaces else "☐ MRKT",
                    callback_data="toggle_marketplace_mrkt"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")
            ]
        ])
        
        enabled_list = ', '.join(sorted(enabled_marketplaces)) if enabled_marketplaces else "Нет"
        
        await callback.message.edit_text(
            f"⚙️ <b>Настройки маркетплейсов</b>\n\n"
            f"Включенные маркетплейсы: <b>{enabled_list}</b>\n\n"
            f"Нажмите на маркетплейс, чтобы включить/выключить:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in callback_menu_settings: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при получении настроек", show_alert=True)


@dp.callback_query(lambda c: c.data and c.data.startswith("toggle_marketplace_"))
async def callback_toggle_marketplace(callback: types.CallbackQuery):
    """Обработка переключения маркетплейса"""
    marketplace = callback.data.replace("toggle_marketplace_", "")
    
    if marketplace not in ['portals', 'tonnel', 'mrkt']:
        await callback.answer("❌ Неверный выбор маркетплейса", show_alert=True)
        return
    
    if not db_pool:
        await callback.answer("❌ База данных не подключена", show_alert=True)
        return
    
    try:
        logger.info(f"[settings] toggle marketplace={marketplace} user={callback.from_user.id}")
        new_state = True
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Переключаем конкретный маркетплейс
                await cur.execute("""
                    SELECT enabled FROM user_marketplaces 
                    WHERE user_id = %s AND marketplace = %s
                """, (callback.from_user.id, marketplace))
                result = await cur.fetchone()
                
                current_state = result[0] if result else False
                new_state = not current_state
                
                await cur.execute("""
                    INSERT INTO user_marketplaces (user_id, marketplace, enabled)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE enabled = %s
                """, (callback.from_user.id, marketplace, new_state, new_state))
                
                await conn.commit()
        
        marketplace_names = {
            'portals': 'Portals',
            'tonnel': 'Tonnel',
            'mrkt': 'MRKT'
        }
        current_name = marketplace_names.get(marketplace, marketplace)
        
        await callback.answer(f"✅ {current_name} {'включен' if new_state else 'выключен'}")
        
        # Обновляем сообщение - получаем актуальные настройки
        enabled_marketplaces = set()
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT marketplace FROM user_marketplaces 
                    WHERE user_id = %s AND enabled = TRUE
                """, (callback.from_user.id,))
                results = await cur.fetchall()
                for (mp,) in results:
                    enabled_marketplaces.add(mp)
        
        # Создаем клавиатуру для выбора маркетплейсов (чекбоксы) — без GetGems и без кнопки "Все"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Portals" if 'portals' in enabled_marketplaces else "☐ Portals",
                    callback_data="toggle_marketplace_portals"
                ),
                InlineKeyboardButton(
                    text="✅ Tonnel" if 'tonnel' in enabled_marketplaces else "☐ Tonnel",
                    callback_data="toggle_marketplace_tonnel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ MRKT" if 'mrkt' in enabled_marketplaces else "☐ MRKT",
                    callback_data="toggle_marketplace_mrkt"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")
            ]
        ])
        
        enabled_list = ', '.join(sorted(enabled_marketplaces)) if enabled_marketplaces else "Нет"
        
        try:
            await callback.message.edit_text(
                f"⚙️ <b>Настройки маркетплейсов</b>\n\n"
                f"Включенные маркетплейсы: <b>{enabled_list}</b>\n\n"
                f"Нажмите на маркетплейс, чтобы включить/выключить:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as edit_error:
            # Игнорируем ошибку "message is not modified"
            if "message is not modified" not in str(edit_error):
                logger.error(f"Error editing message in callback_toggle_marketplace: {edit_error}")
        
    except Exception as e:
        logger.error(f"Error in callback_toggle_marketplace: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при сохранении настроек", show_alert=True)



# Команды /stop и /get удалены

# Кэш для хранения списка всех подарков
_all_gifts_cache = {}  # marketplace -> set of gift names
_all_gifts_cache_time = {}  # marketplace -> timestamp
CACHE_TTL = 3600  # 1 час

async def get_all_gift_names_from_marketplace(marketplace: str) -> set:
    """Получить все уникальные названия подарков с маркетплейса"""
    global auth_token
    
    # Проверяем кэш
    current_time = asyncio.get_event_loop().time()
    if marketplace in _all_gifts_cache and marketplace in _all_gifts_cache_time:
        if current_time - _all_gifts_cache_time[marketplace] < CACHE_TTL:
            return _all_gifts_cache[marketplace]
    
    gift_names = set()
    
    try:
        if marketplace == 'portals':
            portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
            if not portals_auth:
                if not auth_token:
                    auth_token = await init_auth()
                portals_auth = auth_token
            
            if portals_auth:
                # Сначала пробуем получить все коллекции через API
                try:
                    import requests as req_lib
                    try:
                        from curl_cffi import requests as curl_requests
                        requests_lib = curl_requests
                    except ImportError:
                        requests_lib = req_lib
                    
                    # Получаем список всех коллекций
                    # Используем URL из portalsmp
                    from portalsmp import PORTALS_API_URL
                    collections_url = f"{PORTALS_API_URL}collections?limit=1000"
                    headers = {
                        "Authorization": portals_auth if portals_auth.startswith('tma ') else f"tma {portals_auth}",
                        "Accept": "application/json, text/plain, */*",
                        "Origin": "https://portal-market.com",
                        "Referer": "https://portal-market.com/",
                    }
                    
                    if hasattr(requests_lib, 'Session') and hasattr(requests_lib.Session, 'impersonate'):
                        session = requests_lib.Session(impersonate="chrome110")
                        response = session.get(collections_url, headers=headers, timeout=30)
                    else:
                        response = requests_lib.get(collections_url, headers=headers, timeout=30)
                    
                    if response.status_code == 200:
                        data = response.json()
                        collections = data.get('collections') or data.get('results') or []
                        
                        for collection in collections:
                            if isinstance(collection, dict):
                                name = collection.get('name') or collection.get('collectionName')
                                if name:
                                    gift_names.add(name)
                        
                        logger.info(f"[gifts] Portals: Got {len(collections)} collections from API, total unique: {len(gift_names)}")
                    else:
                        logger.warning(f"[gifts] Portals: Collections API returned {response.status_code}, using search fallback")
                except Exception as e:
                    logger.warning(f"[gifts] Portals: Error getting collections: {e}, using search fallback")
                
                # Дополнительно получаем подарки через пагинацию поиска
                limit = 100
                offset = 0
                seen_names = set(gift_names)  # Используем уже полученные имена
                max_iterations = 100  # Максимум 10000 дополнительных подарков
                
                logger.info(f"[gifts] Portals: Starting to fetch additional gifts through search...")
                
                for iteration in range(max_iterations):
                    try:
                        # Используем API напрямую с offset для пагинации
                        from urllib.parse import quote_plus
                        import requests as req_lib
                        try:
                            from curl_cffi import requests as curl_requests
                            requests_lib = curl_requests
                        except ImportError:
                            requests_lib = req_lib
                        
                        from portalsmp import PORTALS_API_URL
                        url = f"{PORTALS_API_URL}nfts/search?offset={offset}&limit={limit}&sort_by=listed_at+desc&status=listed&exclude_bundled=true&premarket_status=all"
                        
                        headers = {
                            "Authorization": portals_auth if portals_auth.startswith('tma ') else f"tma {portals_auth}",
                            "Accept": "application/json, text/plain, */*",
                            "Origin": "https://portal-market.com",
                            "Referer": "https://portal-market.com/",
                        }
                        
                        if hasattr(requests_lib, 'Session') and hasattr(requests_lib.Session, 'impersonate'):
                            session = requests_lib.Session(impersonate="chrome110")
                            response = session.get(url, headers=headers, timeout=30)
                        else:
                            response = requests_lib.get(url, headers=headers, timeout=30)
                        
                        if response.status_code == 429:
                            logger.warning(f"Portals rate limit, waiting...")
                            await asyncio.sleep(5)
                            continue
                        
                        response.raise_for_status()
                        data = response.json()
                        
                        items = data.get('results') or data.get('items') or []
                        
                        if not items:
                            logger.info(f"[gifts] Portals: No more items at offset {offset}, total unique gifts: {len(gift_names)}")
                            break
                        
                        batch_names = 0
                        for item in items:
                            if isinstance(item, dict):
                                name = item.get('name') or item.get('collectionName') or item.get('gift_name')
                            elif hasattr(item, 'name'):
                                name = item.name
                            else:
                                continue
                            
                            if name and name not in seen_names:
                                gift_names.add(name)
                                seen_names.add(name)
                                batch_names += 1
                        
                        logger.debug(f"[gifts] Portals: Offset {offset}, got {len(items)} items, {batch_names} new unique names, total: {len(gift_names)}")
                        
                        if len(items) < limit:
                            logger.info(f"[gifts] Portals: Reached end, got {len(gift_names)} unique gift names")
                            break
                        
                        offset += limit
                        await asyncio.sleep(0.1)  # Оптимизированная задержка между запросами
                        
                    except Exception as e:
                        logger.error(f"Error fetching gifts from Portals at offset {offset}: {e}")
                        if "429" in str(e) or "rate limit" in str(e).lower():
                            await asyncio.sleep(5)
                            continue
                        break
                
                logger.info(f"[gifts] Portals: Finished fetching, total unique gift names: {len(gift_names)}")
                        
        elif marketplace == 'tonnel' and search_tonnel:
            try:
                logger.info(f"[gifts] Starting to fetch all gifts from Tonnel...")
                seen_names = set()
                page = 1
                max_pages = 100  # Максимум 3000 подарков (30 на страницу)
                
                for page in range(1, max_pages + 1):
                    try:
                        # Используем прямой API запрос для пагинации
                        import requests as req_lib
                        try:
                            from curl_cffi import requests as curl_requests
                            requests_lib = curl_requests
                        except ImportError:
                            requests_lib = req_lib
                        
                        url = "https://gifts2.tonnel.network/api/pageGifts"
                        headers = {
                            "accept": "*/*",
                            "content-type": "application/json",
                            "origin": "https://market.tonnel.network",
                            "referer": "https://market.tonnel.network/",
                            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36",
                        }
                        
                        json_data = {
                            "page": page,
                            "limit": 30,  # Максимум для Tonnel
                            "sort": '{"message_post_time":-1,"gift_id":-1}',
                            "filter": '{"price":{"$exists":true},"refunded":{"$ne":true},"buyer":{"$exists":false},"export_at":{"$exists":true},"asset":"TON"}',
                            "ref": 0,
                            "price_range": None,
                            "user_auth": TONNEL_AUTH or "",
                        }
                        
                        if hasattr(requests_lib, 'Session') and hasattr(requests_lib.Session, 'impersonate'):
                            session = requests_lib.Session(impersonate="chrome131")
                            response = session.post(url, headers=headers, json=json_data, timeout=30)
                        else:
                            response = requests_lib.post(url, headers=headers, json=json_data, timeout=30)
                        
                        response.raise_for_status()
                        data = response.json()
                        
                        items = data.get('items') or data.get('data') or []
                        
                        if not items:
                            logger.info(f"[gifts] Tonnel: No more items at page {page}, total unique gifts: {len(gift_names)}")
                            break
                        
                        batch_names = 0
                        for item in items:
                            if isinstance(item, dict):
                                name = item.get('gift_name') or item.get('name') or item.get('collectionName')
                                if name and name not in seen_names:
                                    gift_names.add(name)
                                    seen_names.add(name)
                                    batch_names += 1
                        
                        logger.debug(f"[gifts] Tonnel: Page {page}, got {len(items)} items, {batch_names} new unique names, total: {len(gift_names)}")
                        
                        if len(items) < 30:
                            logger.info(f"[gifts] Tonnel: Reached end, got {len(gift_names)} unique gift names")
                            break
                        
                        await asyncio.sleep(0.1)  # Оптимизированная задержка между запросами
                        
                    except Exception as e:
                        logger.error(f"Error fetching gifts from Tonnel at page {page}: {e}")
                        break
                
                logger.info(f"[gifts] Tonnel: Finished fetching, total unique gift names: {len(gift_names)}")
            except Exception as e:
                logger.error(f"Error fetching gifts from Tonnel: {e}", exc_info=True)
                
        elif marketplace == 'mrkt' and search_mrkt and MRKT_AUTH:
            try:
                items = search_mrkt(limit=100, sort="price_asc", auth_token=MRKT_AUTH)
                if isinstance(items, dict):
                    items = items.get('gifts') or items.get('results') or items.get('items') or []
                elif not isinstance(items, list):
                    items = []
                
                seen_ids = set()
                for item in items:
                    if isinstance(item, dict):
                        name = item.get('name') or item.get('collectionName') or item.get('gift_name')
                        item_id = item.get('id') or item.get('giftId') or item.get('giftIdString')
                        if name and item_id and item_id not in seen_ids:
                            gift_names.add(name)
                            seen_ids.add(item_id)
            except Exception as e:
                logger.error(f"Error fetching gifts from MRKT: {e}")
    
    except Exception as e:
        logger.error(f"Error in get_all_gift_names_from_marketplace for {marketplace}: {e}")
    
    # Обновляем кэш
    _all_gifts_cache[marketplace] = gift_names
    _all_gifts_cache_time[marketplace] = current_time
    
    return gift_names

async def get_all_gift_names() -> set:
    """Получить все уникальные названия подарков со всех маркетплейсов"""
    all_names = set()
    
    for marketplace in ['portals', 'tonnel', 'mrkt']:
        names = await get_all_gift_names_from_marketplace(marketplace)
        all_names.update(names)
        await asyncio.sleep(0.05)  # Оптимизированная задержка между маркетплейсами
    
    return all_names

async def get_models_for_gift(gift_name: str, marketplace: str = None) -> set:
    """Получить все модели для конкретного подарка"""
    global auth_token
    models = set()
    
    marketplaces = [marketplace] if marketplace else ['portals', 'tonnel', 'mrkt']
    
    for mp in marketplaces:
        try:
            if mp == 'portals':
                portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                if not portals_auth:
                    if not auth_token:
                        auth_token = await init_auth()
                    portals_auth = auth_token
                
                if portals_auth:
                    try:
                        if inspect.iscoroutinefunction(search):
                            items = await search(gift_name=gift_name, limit=100, sort="price_asc", authData=portals_auth)
                        else:
                            items = await asyncio.to_thread(search, gift_name=gift_name, limit=100, sort="price_asc", authData=portals_auth)
                        
                        if isinstance(items, dict):
                            items = items.get('results') or items.get('items') or []
                        elif not isinstance(items, list):
                            continue
                        
                        for item in items:
                            if isinstance(item, dict):
                                model = item.get('model') or item.get('modelName') or item.get('model_name')
                            elif hasattr(item, 'model'):
                                model = item.model
                            else:
                                continue
                            
                            if model:
                                models.add(model)
                    except Exception as e:
                        logger.error(f"Error getting models from Portals for {gift_name}: {e}")
                        
            elif mp == 'tonnel' and search_tonnel:
                try:
                    items = search_tonnel(gift_name=gift_name, limit=100, sort="price_asc", authData=TONNEL_AUTH)
                    if isinstance(items, dict):
                        items = items.get('results') or items.get('items') or items.get('gifts') or []
                    elif not isinstance(items, list):
                        continue
                    
                    for item in items:
                        if isinstance(item, dict):
                            model = item.get('model') or item.get('modelName') or item.get('model_name')
                            if model:
                                models.add(model)
                except Exception as e:
                    logger.error(f"Error getting models from Tonnel for {gift_name}: {e}")
                    
            elif mp == 'mrkt' and search_mrkt and MRKT_AUTH:
                try:
                    items = search_mrkt(gift_name=gift_name, limit=100, sort="price_asc", auth_token=MRKT_AUTH)
                    if isinstance(items, dict):
                        items = items.get('gifts') or items.get('results') or items.get('items') or []
                    elif not isinstance(items, list):
                        continue
                    
                    for item in items:
                        if isinstance(item, dict):
                            model = item.get('modelName') or item.get('model') or item.get('model_name')
                            if model:
                                models.add(model)
                except Exception as e:
                    logger.error(f"Error getting models from MRKT for {gift_name}: {e}")
        except Exception as e:
            logger.error(f"Error in get_models_for_gift for {mp}: {e}")
    
    return models

def paginate_items(items: list, page: int = 0, per_page: int = 10) -> tuple:
    """Разбить список на страницы"""
    start = page * per_page
    end = start + per_page
    return items[start:end], len(items), (len(items) + per_page - 1) // per_page

def filter_items_by_search(items: list, search_query: str) -> list:
    """Отфильтровать список по поисковому запросу"""
    if not search_query:
        return items
    
    search_lower = search_query.lower()
    return [item for item in items if search_lower in item.lower()]

def group_by_alphabet(items: list) -> dict:
    """Группировать элементы по первой букве алфавита"""
    groups = {}
    for item in items:
        first_char = item[0].upper() if item else '0'
        if not first_char.isalpha():
            first_char = '0-9'
        if first_char not in groups:
            groups[first_char] = []
        groups[first_char].append(item)
    
    # Сортируем группы и элементы внутри групп
    for key in groups:
        groups[key].sort()
    
    return dict(sorted(groups.items()))

@dp.callback_query(lambda c: c.data == "menu_add")
async def callback_menu_add(callback: types.CallbackQuery, state: FSMContext):
    """Обработка нажатия на кнопку 'Добавить подарок' - новая система с пагинацией"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем все подарки
    await callback.message.edit_text("⏳ Загружаю список подарков...")
    all_gifts = await get_all_gift_names()
    
    if not all_gifts:
        await callback.message.edit_text("❌ Не удалось загрузить подарки. Попробуйте позже.")
        await callback.answer()
        return
    
    # Группируем по алфавиту
    gifts_list = sorted(list(all_gifts))
    grouped = group_by_alphabet(gifts_list)
    alphabet_keys = list(grouped.keys())
    
    if not alphabet_keys:
        await callback.message.edit_text("❌ Список подарков пуст.")
        await callback.answer()
        return
    
    # Сохраняем данные в состояние
    await state.update_data(
        all_gifts=grouped,
        alphabet_keys=alphabet_keys,
        current_letter_index=0,
        search_query=""
    )
    
    # Показываем первую страницу
    await show_gifts_page(callback, state, 0)
    await callback.answer()

async def show_gifts_page(callback: types.CallbackQuery, state: FSMContext, letter_index: int = None):
    """Показать страницу с подарками по алфавиту"""
    data = await state.get_data()
    grouped = data.get('all_gifts', {})
    alphabet_keys = data.get('alphabet_keys', [])
    search_query = data.get('search_query', '')
    
    if letter_index is None:
        letter_index = data.get('current_letter_index', 0)
    
    if not alphabet_keys:
        await callback.message.edit_text("❌ Список подарков пуст.")
        return
    
    # Применяем поиск если есть
    if search_query:
        filtered_gifts = []
        for letter, gifts in grouped.items():
            filtered = filter_items_by_search(gifts, search_query)
            filtered_gifts.extend(filtered)
        filtered_gifts = sorted(filtered_gifts)
    else:
        # Показываем подарки для текущей буквы
        if letter_index >= len(alphabet_keys):
            letter_index = 0
        current_letter = alphabet_keys[letter_index]
        filtered_gifts = grouped.get(current_letter, [])
    
    if not filtered_gifts:
        text = f"🔍 Поиск: {search_query}\n\n❌ Подарки не найдены."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="gifts_back")],
            [InlineKeyboardButton(text="🔍 Поиск", callback_data="gifts_search")],
            [InlineKeyboardButton(text="✅ Любые подарки", callback_data="gift_select_any")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # Разбиваем на страницы (по 15 подарков на страницу)
    page = data.get('current_page', 0)
    page_items, total_items, total_pages = paginate_items(filtered_gifts, page, 15)
    
    # Формируем текст
    if search_query:
        text = f"🔍 Поиск: <b>{search_query}</b>\n\n"
    else:
        current_letter = alphabet_keys[letter_index] if letter_index < len(alphabet_keys) else alphabet_keys[0]
        text = f"📦 Подарки (буква <b>{current_letter}</b>)\n\n"
    
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    # Создаем кнопки с подарками
    keyboard_buttons = []
    for gift_name in page_items:
        keyboard_buttons.append([InlineKeyboardButton(
            text=gift_name,
            callback_data=f"gift_select_{gift_name}"
        )])
    
    # Кнопки навигации
    nav_buttons = []
    
    if search_query:
        # В режиме поиска показываем навигацию по страницам
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"gifts_page_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"gifts_page_{page + 1}"))
    else:
        # В режиме алфавита показываем навигацию по буквам
        if letter_index > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"gifts_letter_{letter_index - 1}"))
        if letter_index < len(alphabet_keys) - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"gifts_letter_{letter_index + 1}"))
    
    if nav_buttons:
        keyboard_buttons.append(nav_buttons)
    
    # Дополнительные кнопки
    extra_buttons = []
    if not search_query:
        extra_buttons.append(InlineKeyboardButton(text="🔍 Поиск", callback_data="gifts_search"))
    extra_buttons.append(InlineKeyboardButton(text="✅ Любые подарки", callback_data="gift_select_any"))
    keyboard_buttons.append(extra_buttons)
    
    # Возврат в меню добавления подарков
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_add")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await state.update_data(current_letter_index=letter_index, current_page=page)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

# Обработчики для навигации по подаркам
@dp.callback_query(lambda c: c.data and c.data.startswith("gifts_letter_"))
async def callback_gifts_letter(callback: types.CallbackQuery, state: FSMContext):
    """Переключение буквы в списке подарков"""
    letter_index = int(callback.data.split("_")[-1])
    await state.update_data(current_page=0)
    await show_gifts_page(callback, state, letter_index)
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("gifts_page_"))
async def callback_gifts_page(callback: types.CallbackQuery, state: FSMContext):
    """Переключение страницы в списке подарков"""
    page = int(callback.data.split("_")[-1])
    await state.update_data(current_page=page)
    await show_gifts_page(callback, state)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "gifts_search")
async def callback_gifts_search(callback: types.CallbackQuery, state: FSMContext):
    """Начать поиск подарков"""
    await callback.message.edit_text("🔍 Введите название подарка для поиска:")
    await state.set_state(GiftSelection.searching_gifts)
    await callback.answer()

@dp.message(GiftSelection.searching_gifts)
async def process_gifts_search(message: types.Message, state: FSMContext):
    """Обработка поискового запроса"""
    search_query = message.text.strip()
    await state.update_data(search_query=search_query, current_page=0)
    
    # Создаем фейковый callback для показа страницы
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
    
    fake_callback = FakeCallback(message)
    await show_gifts_page(fake_callback, state)
    await state.set_state(GiftSelection.browsing_gifts)

@dp.callback_query(lambda c: c.data == "gifts_back")
async def callback_gifts_back(callback: types.CallbackQuery, state: FSMContext):
    """Вернуться к списку подарков"""
    await state.update_data(search_query="", current_page=0)
    await show_gifts_page(callback, state, 0)
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("gift_select_"))
async def callback_gift_select(callback: types.CallbackQuery, state: FSMContext):
    """Выбор подарка"""
    gift_name = callback.data.replace("gift_select_", "")
    
    if gift_name == "any":
        # Выбраны "любые подарки"
        await state.update_data(selected_gift="ANY", selected_model="ANY")
        await show_price_filter_input(callback, state)
        await callback.answer("✅ Выбраны любые подарки")
        return
    
    # Получаем модели для этого подарка
    await callback.message.edit_text(f"⏳ Загружаю модели для <b>{gift_name}</b>...", parse_mode="HTML")
    models = await get_models_for_gift(gift_name)
    
    if not models:
        await callback.message.edit_text(
            f"❌ Не удалось загрузить модели для <b>{gift_name}</b>.\n\n"
            f"Вы можете добавить подарок без указания модели (будут отслеживаться все модели).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Любые модели", callback_data=f"model_select_any_{gift_name}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_add")]
            ])
        )
        await callback.answer()
        return
    
    # Сохраняем выбранный подарок
    await state.update_data(selected_gift=gift_name, all_models=sorted(list(models)))
    
    # Показываем модели
    await show_models_page(callback, state, 0)
    await callback.answer()

async def show_models_page(callback: types.CallbackQuery, state: FSMContext, page: int = 0):
    """Показать страницу с моделями"""
    data = await state.get_data()
    gift_name = data.get('selected_gift')
    all_models = data.get('all_models', [])
    search_query = data.get('model_search_query', '')
    
    # Применяем поиск если есть
    if search_query:
        filtered_models = filter_items_by_search(all_models, search_query)
    else:
        filtered_models = all_models
    
    if not filtered_models:
        text = f"🎨 Модели для <b>{gift_name}</b>\n\n"
        if search_query:
            text += f"🔍 Поиск: {search_query}\n\n"
        text += "❌ Модели не найдены."
        
        keyboard_buttons = []
        if search_query:
            keyboard_buttons.append([InlineKeyboardButton(text="🔙 К списку моделей", callback_data="models_back")])
        keyboard_buttons.append([InlineKeyboardButton(text="✅ Любые модели", callback_data=f"model_select_any_{gift_name}")])
        keyboard_buttons.append([InlineKeyboardButton(text="🔍 Поиск", callback_data="models_search")])
        keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_add")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        return
    
    # Разбиваем на страницы (по 8 моделей на страницу)
    page_items, total_items, total_pages = paginate_items(filtered_models, page, 8)
    
    # Формируем текст
    text = f"🎨 Модели для <b>{gift_name}</b>\n\n"
    if search_query:
        text += f"🔍 Поиск: <b>{search_query}</b>\n\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    # Создаем кнопки с моделями
    keyboard_buttons = []
    for model in page_items:
        keyboard_buttons.append([InlineKeyboardButton(
            text=model,
            callback_data=f"model_select_{model}_{gift_name}"
        )])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"models_page_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"models_page_{page + 1}"))
    
    if nav_buttons:
        keyboard_buttons.append(nav_buttons)
    
    # Дополнительные кнопки
    extra_buttons = []
    if not search_query:
        extra_buttons.append(InlineKeyboardButton(text="🔍 Поиск", callback_data="models_search"))
    extra_buttons.append(InlineKeyboardButton(text="✅ Любые модели", callback_data=f"model_select_any_{gift_name}"))
    keyboard_buttons.append(extra_buttons)
    
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_add")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await state.update_data(current_model_page=page)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(lambda c: c.data and c.data.startswith("models_page_"))
async def callback_models_page(callback: types.CallbackQuery, state: FSMContext):
    """Переключение страницы в списке моделей"""
    page = int(callback.data.split("_")[-1])
    await show_models_page(callback, state, page)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "models_search")
async def callback_models_search(callback: types.CallbackQuery, state: FSMContext):
    """Начать поиск моделей"""
    await callback.message.edit_text("🔍 Введите название модели для поиска:")
    await state.set_state(GiftSelection.searching_models)
    await callback.answer()

@dp.message(GiftSelection.searching_models)
async def process_models_search(message: types.Message, state: FSMContext):
    """Обработка поискового запроса моделей"""
    search_query = message.text.strip()
    await state.update_data(model_search_query=search_query, current_model_page=0)
    
    # Создаем фейковый callback для показа страницы
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
    
    fake_callback = FakeCallback(message)
    await show_models_page(fake_callback, state, 0)
    await state.set_state(GiftSelection.browsing_models)

@dp.callback_query(lambda c: c.data == "models_back")
async def callback_models_back(callback: types.CallbackQuery, state: FSMContext):
    """Вернуться к списку моделей"""
    await state.update_data(model_search_query="", current_model_page=0)
    await show_models_page(callback, state, 0)
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("model_select_"))
async def callback_model_select(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели"""
    parts = callback.data.split("_")
    if parts[2] == "any":
        # Выбраны "любые модели"
        gift_name = "_".join(parts[3:])
        await state.update_data(selected_model="ANY")
    else:
        model = "_".join(parts[2:-1])
        gift_name = parts[-1]
        await state.update_data(selected_model=model)
    
    await show_price_filter_input(callback, state)
    await callback.answer()

async def show_price_filter_input(callback: types.CallbackQuery, state: FSMContext):
    """Показать ввод фильтра цены"""
    data = await state.get_data()
    gift_name = data.get('selected_gift', 'N/A')
    model = data.get('selected_model', 'N/A')
    
    if gift_name == "ANY":
        gift_text = "любые подарки"
    else:
        gift_text = gift_name
    
    if model == "ANY":
        model_text = "любые модели"
    else:
        model_text = model
    
    text = (
        f"✅ Выбрано:\n"
        f"📦 Подарок: <b>{gift_text}</b>\n"
        f"🎨 Модель: <b>{model_text}</b>\n\n"
        f"💰 Введите фильтр цены (например: 10-30 или 10 или оставьте пустым для всех цен):"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить (все цены)", callback_data="price_filter_skip")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_add")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(GiftSelection.entering_price_filter)

@dp.callback_query(lambda c: c.data == "price_filter_skip")
async def callback_price_filter_skip(callback: types.CallbackQuery, state: FSMContext):
    """Пропустить фильтр цены"""
    await state.update_data(price_filter_min=None, price_filter_max=None)
    await save_gift_selection(callback, state)
    await callback.answer()

@dp.message(GiftSelection.entering_price_filter)
async def process_price_filter(message: types.Message, state: FSMContext):
    """Обработка ввода фильтра цены"""
    price_text = message.text.strip()
    
    min_price = None
    max_price = None
    
    if price_text:
        # Парсим формат "10-30" или "10" или "10-"
        if '-' in price_text:
            parts = price_text.split('-')
            if parts[0].strip():
                try:
                    min_price = float(parts[0].strip())
                except ValueError:
                    await message.answer("❌ Неверный формат. Используйте: 10-30 или 10")
                    return
            if len(parts) > 1 and parts[1].strip():
                try:
                    max_price = float(parts[1].strip())
                except ValueError:
                    await message.answer("❌ Неверный формат. Используйте: 10-30 или 10")
                    return
        else:
            try:
                min_price = float(price_text)
            except ValueError:
                await message.answer("❌ Неверный формат. Используйте: 10-30 или 10")
                return
    
    await state.update_data(price_filter_min=min_price, price_filter_max=max_price)
    
    # Создаем фейковый callback для сохранения
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
    
    fake_callback = FakeCallback(message)
    await save_gift_selection(fake_callback, state)

async def save_gift_selection(callback_or_message, state: FSMContext):
    """Сохранить выбранный подарок и модель в базу данных"""
    data = await state.get_data()
    gift_name = data.get('selected_gift')
    model = data.get('selected_model')
    min_price = data.get('price_filter_min')
    max_price = data.get('price_filter_max')
    
    if isinstance(callback_or_message, types.CallbackQuery):
        user_id = callback_or_message.from_user.id
        message = callback_or_message.message
    else:
        user_id = callback_or_message.from_user.id
        message = callback_or_message
    
    if not gift_name or not model:
        await message.edit_text("❌ Ошибка: не выбран подарок или модель") if hasattr(message, 'edit_text') else await message.answer("❌ Ошибка: не выбран подарок или модель")
        return
    
    try:
        # Сохраняем в базу данных
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Сохраняем подарок
                await cur.execute("""
                    INSERT INTO gifts (name, model, price, floor_price, photo_url, model_rarity, user_id, marketplace)
                    VALUES (%s, %s, 0, 0, NULL, NULL, %s, 'all')
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        model = VALUES(model)
                """, (gift_name, model, user_id))
                
                # Сохраняем фильтр цены
                await cur.execute("""
                    INSERT INTO user_price_filters (user_id, min_price, max_price)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        min_price = VALUES(min_price),
                        max_price = VALUES(max_price)
                """, (user_id, min_price, max_price))
                
                await conn.commit()
        
        # Формируем сообщение
        gift_text = "любые подарки" if gift_name == "ANY" else gift_name
        model_text = "любые модели" if model == "ANY" else model
        price_text = "все цены"
        if min_price is not None or max_price is not None:
            if min_price is not None and max_price is not None:
                price_text = f"{min_price}-{max_price} TON"
            elif min_price is not None:
                price_text = f"от {min_price} TON"
            elif max_price is not None:
                price_text = f"до {max_price} TON"
        
        text = (
            f"✅ <b>Подарок добавлен для отслеживания</b>\n\n"
            f"📦 Подарок: <b>{gift_text}</b>\n"
            f"🎨 Модель: <b>{model_text}</b>\n"
            f"💰 Фильтр цены: <b>{price_text}</b>\n\n"
            f"Парсинг будет работать только для выбранных подарков и моделей с указанным фильтром цены."
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu_main")]
        ])
        
        if hasattr(message, 'edit_text'):
            await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error saving gift selection: {e}", exc_info=True)
        error_text = f"❌ Ошибка при сохранении: {str(e)}"
        if hasattr(message, 'edit_text'):
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)

@dp.message(Command("add"))
async def add_start(message: types.Message, state: FSMContext):
    """Начало процесса добавления подарка"""
    if not await is_allowed_user(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    
    # Сохраняем пользователя в базу данных
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        INSERT INTO bot_users (user_id, username, first_name, last_name, notifications_enabled)
                        VALUES (%s, %s, %s, %s, TRUE)
                        ON DUPLICATE KEY UPDATE
                            username = VALUES(username),
                            first_name = VALUES(first_name),
                            last_name = VALUES(last_name),
                            notifications_enabled = COALESCE(notifications_enabled, TRUE),
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        message.from_user.id,
                        message.from_user.username,
                        message.from_user.first_name,
                        message.from_user.last_name
                    ))
                    await conn.commit()
        except Exception as e:
            logger.error(f"Error saving user: {e}")
    
    await message.answer("Введите название подарка (name):")
    await state.set_state(AddGift.waiting_name)


@dp.message(AddGift.waiting_name)
async def add_name(message: types.Message, state: FSMContext):
    """Обработка ввода названия подарка"""
    await state.update_data(gift_name=message.text)
    await message.answer("Введите модель подарка (model):")
    await state.set_state(AddGift.waiting_model)


@dp.message(AddGift.waiting_model)
async def add_model(message: types.Message, state: FSMContext):
    """Обработка ввода модели и добавление подарка"""
    global auth_token
    
    data = await state.get_data()
    gift_name = data["gift_name"]
    model = message.text

    try:
        # Получаем выбранный маркетплейс пользователя
        marketplace = 'portals'
        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            SELECT marketplace FROM bot_users WHERE user_id = %s
                        """, (message.from_user.id,))
                        result = await cur.fetchone()
                        if result and result[0]:
                            marketplace = result[0]
            except Exception as e:
                logger.warning(f"Error getting marketplace: {e}")

        # Работаем с выбранным маркетплейсом
        if marketplace == 'tonnel':
            # Используем Tonnel API
            if not TONNEL_AUTH:
                await message.answer("Ошибка: TONNEL_AUTH не настроен в конфигурации.")
                await state.clear()
                return
            
            if not search_tonnel:
                await message.answer("Ошибка: библиотека tonnelmp не установлена.")
                await state.clear()
                return
            
            items = search_tonnel(
                gift_name=gift_name,
                model=model if model else None,
                limit=5,
                sort="price_asc",
                authData=TONNEL_AUTH
            )
        elif marketplace == 'mrkt':
            # Используем MRKT API
            if not search_mrkt:
                await message.answer("Ошибка: библиотека mrktmp_wrapper не доступна.")
                await state.clear()
                return
            
            # Используем токен MRKT из конфига
            if not MRKT_AUTH:
                await message.answer("Ошибка: MRKT_AUTH не настроен в конфиге.")
                await state.clear()
                return
            
            items = search_mrkt(
                gift_name=gift_name,
                model=model if model else None,
                limit=5,
                sort="price_asc",
                auth_token=MRKT_AUTH
            )
        else:
            # Используем Portals API
            # Обновляем токен если нужно
            if not auth_token:
                auth_token = await init_auth()
                if not auth_token:
                    await message.answer("Ошибка аутентификации в API. Проверьте API_ID и API_HASH.")
                    await state.clear()
                    return

            # Проверяем, является ли search асинхронной функцией
            if inspect.iscoroutinefunction(search):
                items = await search(
                    gift_name=gift_name,
                    model=model if model else "",
                    limit=5,
                    sort="price_asc",
                    authData=auth_token
                )
            else:
                # Если синхронная, запускаем в отдельном потоке
                items = await asyncio.to_thread(
                    search,
                    gift_name=gift_name,
                    model=model if model else "",
                    limit=5,
                    sort="price_asc",
                    authData=auth_token
                )

        # Официальная библиотека возвращает список напрямую
        if isinstance(items, str):
            await message.answer(f"Ошибка API: {items}")
            if "auth" in items.lower():
                auth_token = await init_auth()
            await state.clear()
            return

        if not isinstance(items, list):
            # Логируем детали для отладки
            logger.error(f"Unexpected API response type: {type(items)}, value: {items}")
            await message.answer(
                f"Ошибка API: неожиданный формат ответа\n"
                f"Тип: {type(items).__name__}\n"
                f"Попробуйте еще раз или проверьте логи."
            )
            await state.clear()
            return

        if not items:
            await message.answer(f"Подарок '{gift_name}' с моделью '{model}' не найден")
            await state.clear()
            return

        gift = items[0]
        
        # aportalsmp возвращает объекты PortalsGift, нужно преобразовать в dict
        if hasattr(gift, '__dict__'):
            gift_dict = gift.__dict__ if hasattr(gift, '__dict__') else {}
        elif hasattr(gift, 'id'):
            # Если это объект PortalsGift
            gift_dict = {
                'id': gift.id,
                'name': gift.name,
                'price': float(gift.price) if hasattr(gift, 'price') else 0,
                'floor_price': float(gift.floor_price) if hasattr(gift, 'floor_price') else 0,
                'photo_url': gift.photo_url if hasattr(gift, 'photo_url') else None,
                'model_rarity': (
                    gift.model_rarity if hasattr(gift, 'model_rarity') and gift.model_rarity else
                    gift.rarity if hasattr(gift, 'rarity') and gift.rarity else
                    gift.model_rarity_name if hasattr(gift, 'model_rarity_name') and gift.model_rarity_name else
                    gift.rarity_name if hasattr(gift, 'rarity_name') and gift.rarity_name else
                    None
                ),
            }
        else:
            gift_dict = gift if isinstance(gift, dict) else {}
        
        # Извлекаем редкость из различных полей
        model_rarity = (
            gift_dict.get('model_rarity') or 
            gift_dict.get('rarity') or 
            gift_dict.get('model_rarity_name') or
            gift_dict.get('rarity_name') or
            'N/A'
        )
        gift_dict['model_rarity'] = model_rarity
        
        # Получаем маркетплейс пользователя
        user_marketplace = 'portals'
        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            SELECT marketplace FROM bot_users WHERE user_id = %s
                        """, (message.from_user.id,))
                        result = await cur.fetchone()
                        if result and result[0]:
                            user_marketplace = result[0]
            except:
                pass
        
        # Получаем флор модели для сохранения
        model_floor_price = None
        try:
            if user_marketplace == 'portals' or user_marketplace == 'all':
                portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                if portals_auth:
                    if inspect.iscoroutinefunction(get_model_floor_price):
                        model_floor_price = await get_model_floor_price(gift_dict.get("name"), model, portals_auth)
                    else:
                        model_floor_price = await asyncio.to_thread(get_model_floor_price, gift_dict.get("name"), model, portals_auth)
            elif user_marketplace == 'tonnel':
                if TONNEL_AUTH and get_tonnel_model_floor_price:
                    model_floor_price = get_tonnel_model_floor_price(gift_dict.get("name"), model, TONNEL_AUTH)
            elif user_marketplace == 'mrkt':
                if MRKT_AUTH and get_mrkt_model_floor_price:
                    model_floor_price = get_mrkt_model_floor_price(gift_dict.get("name"), model, MRKT_AUTH)
        except Exception as e:
            logger.error(f"Error getting model floor price when adding gift: {e}")
        
        await add_gift_to_db(gift_dict, message.from_user.id, model, user_marketplace, model_floor_price)

        marketplace_names = {
            'portals': 'Portals',
            'tonnel': 'Tonnel',
            'mrkt': 'MRKT',
            'all': 'Все маркетплейсы'
        }
        marketplace_name = marketplace_names.get(user_marketplace, 'Portals')
        
        gift_number = gift_dict.get('external_collection_number') or gift_dict.get('gift_num') or gift_dict.get('number') or 'N/A'
        
        caption = (
            f"✅ <b>Подарок добавлен для отслеживания</b>\n\n"
            f"📦 <b>Название:</b> {gift_dict.get('name', 'Unknown')}\n"
            f"🎨 <b>Модель:</b> {model}\n"
            f"🔢 <b>Номер:</b> {gift_number}\n"
            f"💰 <b>Цена:</b> {gift_dict.get('price', 'N/A')} TON\n"
            f"📊 <b>Флор:</b> {gift_dict.get('floor_price', 'N/A')} TON\n"
            f"⭐ <b>Редкость модели:</b> {model_rarity}\n"
            f"🏪 <b>Маркетплейс:</b> {marketplace_name}"
        )

        gift_id = gift_dict.get('id')
        if not gift_id:
            await message.answer(caption + "\n(Ошибка: ID подарка отсутствует)", parse_mode="HTML")
            await state.clear()
            return

        # Создаем кнопку в зависимости от маркетплейса
        if user_marketplace == 'portals':
            url = f"https://t.me/portals/market?startapp=gift_{gift_id}"
            button_text = "🔗 Открыть в Portals"
        elif user_marketplace == 'tonnel':
            url = f"https://t.me/tonnel_network_bot/gift?startapp={gift_id}"
            button_text = "🔗 Открыть в Tonnel"
        elif user_marketplace == 'mrkt':
            # Для MRKT используем хеш из gift_dict
            mrkt_hash = (
                gift_dict.get('mrkt_hash') or 
                gift_dict.get('hash') or 
                gift_dict.get('hash_id') or 
                gift_dict.get('token') or 
                gift_dict.get('uuid') or
                gift_id  # Fallback на обычный ID
            )
            url = f"https://t.me/mrkt/app?startapp={mrkt_hash}"
            button_text = "🔗 Открыть в MRKT"
        else:
            # Неизвестный маркетплейс - не создаем кнопку
            url = None
            button_text = None

        keyboard = None
        if url and button_text:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=button_text, url=url)]
            ])

        photo_url = gift_dict.get('photo_url')
        
        if photo_url:
            try:
                await message.answer_photo(
                    photo=photo_url,
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
                await message.answer(caption + f"\n(Ошибка загрузки фото: {e})", reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(caption + "\n(Фото недоступно)", reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in add_model: {e}", exc_info=True)
        await message.answer(f"Ошибка поиска: {str(e)}")

    await state.clear()


@dp.callback_query(lambda c: c.data == "menu_list")
async def callback_menu_list(callback: types.CallbackQuery):
    """Показать список отслеживаемых подарков с кнопками удаления"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    await show_gifts_list_page(callback, 0)
    await callback.answer()

async def show_gifts_list_page(callback: types.CallbackQuery, page: int = 0):
    """Показать страницу списка подарков"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Получаем все подарки пользователя
                await cur.execute("""
                    SELECT g.name, g.model, 
                           g.price, 
                           g.floor_price, 
                           g.photo_url, 
                           g.model_rarity, 
                           g.user_id, 
                           g.marketplace,
                           g.model_floor_price
                    FROM gifts g
                    WHERE g.user_id = %s
                    ORDER BY g.name, g.model
                """, (callback.from_user.id,))
                all_gifts = await cur.fetchall()
                
                # Удаляем дубликаты вручную (по name и model, игнорируя marketplace)
                seen = set()
                unique_gifts = []
                for gift in all_gifts:
                    # Используем COALESCE для обработки NULL значений
                    model_key = gift.get('model') if gift.get('model') is not None else 'N/A'
                    key = (gift['name'], model_key)
                    if key not in seen:
                        seen.add(key)
                        unique_gifts.append(gift)
                
                gifts = unique_gifts
                logger.info(f"[list] Found {len(gifts)} unique gifts for user {callback.from_user.id} (from {len(all_gifts)} total records)")
                
                # Получаем фильтр цены отдельно (один на пользователя)
                await cur.execute("""
                    SELECT min_price, max_price FROM user_price_filters WHERE user_id = %s
                """, (callback.from_user.id,))
                price_filter = await cur.fetchone()
                
                # Добавляем фильтр цены к каждому подарку
                min_price = price_filter.get('min_price') if price_filter else None
                max_price = price_filter.get('max_price') if price_filter else None
                for gift in gifts:
                    gift['min_price'] = min_price
                    gift['max_price'] = max_price

        if not gifts:
            text = "📋 У вас нет отслеживаемых подарков.\n\nИспользуйте кнопку 'Добавить подарок' для добавления."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить подарок", callback_data="menu_add")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
            ])
            await callback.message.edit_text(text, reply_markup=keyboard)
            return

        # Разбиваем на страницы (по 5 подарков на страницу)
        page_items, total_items, total_pages = paginate_items(gifts, page, 5)
        
        text = f"📋 <b>Ваши отслеживаемые подарки</b>\n\n"
        text += f"Всего подарков: <b>{total_items}</b>\n"
        text += f"Страница {page + 1} из {total_pages}\n\n"
        
        logger.debug(f"[list] Showing page {page + 1}/{total_pages}, {len(page_items)} items on page, {total_items} total")
        
        keyboard_buttons = []
        for gift in page_items:
            gift_name = gift['name']
            model = gift['model'] or 'N/A'
            
            # Формируем текст для кнопки
            if gift_name == "ANY":
                gift_text = "Любые подарки"
            else:
                gift_text = gift_name
            
            if model == "ANY":
                model_text = "любые модели"
            else:
                model_text = model
            
            # Получаем фильтр цены
            price_text = "все цены"
            min_price = gift.get('min_price')
            max_price = gift.get('max_price')
            if min_price is not None or max_price is not None:
                if min_price is not None and max_price is not None:
                    price_text = f"{min_price}-{max_price} TON"
                elif min_price is not None:
                    price_text = f"от {min_price} TON"
                elif max_price is not None:
                    price_text = f"до {max_price} TON"
            
            button_text = f"📦 {gift_text} | 🎨 {model_text} | 💰 {price_text}"
            # Ограничиваем длину текста кнопки
            if len(button_text) > 60:
                button_text = button_text[:57] + "..."
            
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"gift_info_{gift['name']}_{gift['model']}"
                )
            ])
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"❌ Удалить {gift_text}",
                    callback_data=f"gift_delete_{gift['name']}_{gift['model']}"
                )
            ])
        
        # Кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"list_page_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"list_page_{page + 1}"))
        
        if nav_buttons:
            keyboard_buttons.append(nav_buttons)
        
        keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error in show_gifts_list_page: {e}", exc_info=True)
        await callback.answer("❌ Ошибка получения списка", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith("list_page_"))
async def callback_list_page(callback: types.CallbackQuery):
    """Переключение страницы в списке подарков"""
    page = int(callback.data.split("_")[-1])
    await show_gifts_list_page(callback, page)
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("gift_delete_"))
async def callback_gift_delete(callback: types.CallbackQuery):
    """Удаление подарка из списка"""
    parts = callback.data.split("_")
    gift_name = "_".join(parts[2:-1])
    model = parts[-1]
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Удаляем все записи с таким name и model (независимо от marketplace)
                await cur.execute("""
                    DELETE FROM gifts 
                    WHERE user_id = %s AND name = %s AND model = %s
                """, (callback.from_user.id, gift_name, model))
                deleted_count = cur.rowcount
                await conn.commit()
        
        if deleted_count > 0:
            await callback.answer(f"✅ Подарок {gift_name} ({model}) удален")
        else:
            await callback.answer(f"⚠️ Подарок не найден", show_alert=True)
        
        # Обновляем список - показываем первую страницу
        await show_gifts_list_page(callback, 0)
        
    except Exception as e:
        logger.error(f"Error deleting gift: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при удалении", show_alert=True)

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    """Показать список отслеживаемых подарков (старая команда, перенаправляет на новую систему)"""
    # Создаем фейковый callback
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = message.from_user
    
    fake_callback = FakeCallback(message)
    await show_gifts_list_page(fake_callback, 0)


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Показать статистику"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT COUNT(*) as total FROM gifts WHERE user_id = %s",
                    (message.from_user.id,)
                )
                result = await cur.fetchone()
                total = result['total'] if result else 0

                await cur.execute("""
                    SELECT COUNT(DISTINCT CONCAT(name, model)) as unique_count 
                    FROM gifts WHERE user_id = %s
                """, (message.from_user.id,))
                result = await cur.fetchone()
                unique = result['unique_count'] if result else 0

        await message.answer(
            f"📊 Статистика:\n\n"
            f"Всего подарков: {total}\n"
            f"Уникальных: {unique}"
        )
    except Exception as e:
        logger.error(f"Error in cmd_stats: {e}", exc_info=True)
        await message.answer(f"Ошибка получения статистики: {str(e)}")


async def check_prices():
    """Проверка изменения цен на отслеживаемые подарки"""
    global auth_token
    
    if not db_pool:
        return
        
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM gifts")
            gifts = await cur.fetchall()

        for gift in gifts:
            name = gift["name"]
            model = gift["model"]
            user_id = gift["user_id"]
            old_price = gift["price"]
            old_floor = gift["floor_price"]
            marketplace = gift.get("marketplace", "portals")

            # Пропускаем специальное значение "ANY" - это не валидное имя подарка для поиска
            if name and name.upper() == "ANY":
                logger.debug(f"Skipping gift with name 'ANY' for user {user_id} - this is a special value, not a real gift name")
                continue

            if model is None:
                logger.warning(f"Skipping gift with name '{name}' for user {user_id} due to None model")
                continue
            
            # Пропускаем записи с model="ANY" - это специальное значение, не валидное имя модели
            if model and model.upper() == "ANY":
                logger.debug(f"Skipping gift with name '{name}' and model 'ANY' for user {user_id} - 'ANY' is a special value, not a real model name")
                continue

            try:
                # Работаем с выбранным маркетплейсом
                if marketplace == 'tonnel':
                    # Tonnel
                    if not TONNEL_AUTH:
                        logger.warning(f"TONNEL_AUTH not configured, skipping gift {name} for user {user_id}")
                        continue
                    
                    if not search_tonnel:
                        logger.warning(f"search_tonnel not available, skipping gift {name} for user {user_id}")
                        continue
                    
                    items = search_tonnel(
                        gift_name=name,
                        model=model if model else None,
                        limit=1,
                        sort="price_asc",
                        authData=TONNEL_AUTH
                    )
                elif marketplace == 'mrkt':
                    # MRKT
                    if not search_mrkt:
                        logger.warning(f"search_mrkt not available, skipping gift {name} for user {user_id}")
                        continue
                    
                    # Используем токен MRKT из конфига
                    if not MRKT_AUTH:
                        logger.warning(f"MRKT_AUTH not configured, skipping gift {name} for user {user_id}")
                        continue
                    
                    items = search_mrkt(
                        gift_name=name,
                        model=model if model else None,
                        limit=1,
                        sort="price_asc",
                        auth_token=MRKT_AUTH
                    )
                else:
                    # Portals (по умолчанию)
                    if not auth_token:
                        auth_token = await init_auth()
                        if not auth_token:
                            logger.error("Cannot check prices: auth failed")
                            continue

                    # Проверяем, является ли search асинхронной функцией
                    if inspect.iscoroutinefunction(search):
                        items = await search(
                            gift_name=name,
                            model=model if model else "",
                            limit=1,
                            sort="price_asc",
                            authData=auth_token
                        )
                    else:
                        # Если синхронная, запускаем в отдельном потоке
                        items = await asyncio.to_thread(
                            search,
                            gift_name=name,
                            model=model if model else "",
                            limit=1,
                            sort="price_asc",
                            authData=auth_token
                        )

                # Официальная библиотека возвращает список напрямую
                if isinstance(items, str):
                    logger.error(f"API error for {name} ({model}): {items}")
                    if "auth" in items.lower():
                        auth_token = await init_auth()
                    continue

                if not isinstance(items, list):
                    logger.warning(f"No items returned for {name} ({model}) - unexpected format")
                    continue

                if not items:
                    logger.warning(f"No items found for {name} ({model})")
                    continue

                current = items[0]
                
                # Обрабатываем как объект PortalsGift или dict
                if hasattr(current, 'price'):
                    # Это объект PortalsGift из aportalsmp
                    new_price = float(current.price) if current.price else float('inf')
                    new_floor = float(current.floor_price) if hasattr(current, 'floor_price') and current.floor_price else float('inf')
                    current_id = current.id if hasattr(current, 'id') else None
                    current_photo_url = current.photo_url if hasattr(current, 'photo_url') else None
                    current_model_rarity = (
                        current.model_rarity if hasattr(current, 'model_rarity') and current.model_rarity else
                        current.rarity if hasattr(current, 'rarity') and current.rarity else
                        current.model_rarity_name if hasattr(current, 'model_rarity_name') and current.model_rarity_name else
                        current.rarity_name if hasattr(current, 'rarity_name') and current.rarity_name else
                        None
                    )
                else:
                    # Это dict
                    new_price = float(current.get("price", float('inf')))
                    new_floor = float(current.get("floor_price", float('inf')))
                    current_id = current.get('id')
                    current_photo_url = current.get('photo_url')
                    current_model_rarity = (
                        current.get('model_rarity') or 
                        current.get('rarity') or 
                        current.get('model_rarity_name') or
                        current.get('rarity_name') or
                        None
                    )
                
                # Получаем флор модели для сравнения
                new_model_floor = None
                try:
                    if marketplace == 'portals':
                        portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                        if portals_auth:
                            if inspect.iscoroutinefunction(get_model_floor_price):
                                new_model_floor = await get_model_floor_price(name, model, portals_auth)
                            else:
                                new_model_floor = await asyncio.to_thread(get_model_floor_price, name, model, portals_auth)
                    elif marketplace == 'tonnel':
                        if TONNEL_AUTH and get_tonnel_model_floor_price:
                            new_model_floor = get_tonnel_model_floor_price(name, model, TONNEL_AUTH)
                    elif marketplace == 'mrkt':
                        if MRKT_AUTH and get_mrkt_model_floor_price:
                            new_model_floor = get_mrkt_model_floor_price(name, model, MRKT_AUTH)
                except Exception as e:
                    logger.error(f"Error getting model floor price for {name} / {model} on {marketplace}: {e}")
                
                # Получаем старый флор модели из базы данных
                old_model_floor = gift.get("model_floor_price")
                if old_model_floor is None:
                    old_model_floor = old_floor  # Используем старый флор подарка как fallback

                # Проверяем снижение цены или флора (цены подарка или флора модели)
                price_dropped = new_price < old_price
                floor_dropped = new_floor < old_floor
                model_floor_dropped = new_model_floor is not None and old_model_floor is not None and new_model_floor < old_model_floor
                
                if price_dropped or floor_dropped or model_floor_dropped:
                    marketplace_names = {
                        'portals': 'Portals',
                        'tonnel': 'Tonnel',
                        'mrkt': 'MRKT'
                    }
                    marketplace_name = marketplace_names.get(marketplace, 'Portals')
                    
                    caption = (
                        f"📦 Название: {name}\n"
                        f"🎨 Модель: {model}\n"
                    )
                    
                    if price_dropped:
                        caption += f"💰 Старая цена: {old_price:.2f} TON → Новая: {new_price:.2f} TON\n"
                    
                    if floor_dropped:
                        caption += f"📊 Старый флор: {old_floor:.2f} TON → Новый: {new_floor:.2f} TON\n"
                    
                    if model_floor_dropped:
                        caption += f"📊 Старый флор модели: {old_model_floor:.2f} TON → Новый: {new_model_floor:.2f} TON\n"
                    
                    caption += f"🏪 Маркетплейс: {marketplace_name}"

                    # Создаем кнопку в зависимости от маркетплейса
                    if marketplace == 'portals':
                        url = f"https://t.me/portals/market?startapp=gift_{current_id}"
                        button_text = "🔗 Открыть в Portals"
                    elif marketplace == 'tonnel':
                        url = f"https://t.me/tonnel_network_bot/gift?startapp={current_id}"
                        button_text = "🔗 Открыть в Tonnel"
                    elif marketplace == 'mrkt':
                        # Для MRKT используем хеш из поля mrkt_hash или ищем в других полях
                        mrkt_hash = (
                            current.get('mrkt_hash') or 
                            current.get('hash') or 
                            current.get('hash_id') or 
                            current.get('token') or 
                            current.get('uuid') or
                            current.get('app_id') or
                            current_id  # Fallback на обычный ID если хеш не найден
                        )
                        url = f"https://t.me/mrkt/app?startapp={mrkt_hash}"
                        button_text = "🔗 Открыть в MRKT"
                        logger.info(f"MRKT link for gift: id={current_id}, mrkt_hash={current.get('mrkt_hash')}, final_hash={mrkt_hash}")
                    else:
                        # Неизвестный маркетплейс - не создаем кнопку
                        url = None
                        button_text = None
                    
                    keyboard = None
                    if url and button_text:
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text=button_text,
                                url=url
                            )]
                        ])

                    if current_photo_url:
                        try:
                            await bot.send_photo(
                                chat_id=user_id,
                                photo=current_photo_url,
                                caption=caption,
                                reply_markup=keyboard
                            )
                        except Exception as e:
                            logger.error(f"Error sending photo in notification for user {user_id}: {e}")
                            await bot.send_message(
                                chat_id=user_id,
                                text=caption + f"\n(Ошибка загрузки фото: {e})",
                                reply_markup=keyboard
                            )
                    else:
                        await bot.send_message(
                            chat_id=user_id,
                            text=caption + "\n(Фото недоступно)",
                            reply_markup=keyboard
                        )

                    async with conn.cursor() as cur:
                        # Проверяем наличие колонки model_floor_price
                        try:
                            await cur.execute("""
                            UPDATE gifts 
                            SET price = %s, floor_price = %s, photo_url = %s, model_rarity = %s, model_floor_price = %s
                            WHERE name = %s AND model = %s AND user_id = %s AND marketplace = %s
                            """, (
                                new_price,
                                new_floor,
                                current_photo_url,
                                current_model_rarity,
                                new_model_floor,
                                name,
                                model,
                                user_id,
                                marketplace
                            ))
                        except Exception as e:
                            # Если колонка model_floor_price не существует, обновляем без неё
                            logger.warning(f"Column model_floor_price might not exist: {e}")
                            await cur.execute("""
                            UPDATE gifts 
                            SET price = %s, floor_price = %s, photo_url = %s, model_rarity = %s
                            WHERE name = %s AND model = %s AND user_id = %s AND marketplace = %s
                            """, (
                                new_price,
                                new_floor,
                                current_photo_url,
                                current_model_rarity,
                                name,
                                model,
                                user_id,
                                marketplace
                            ))
                        await conn.commit()
            except Exception as e:
                logger.error(f"Error checking price for {name} ({model}) for user {user_id}: {e}", exc_info=True)


async def check_new_gifts():
    """Проверка новых подарков на маркетплейсе (старая функция, оставлена для совместимости)"""
    # Эта функция больше не используется, но оставлена для совместимости
    return


# Эта функция больше не используется, удалена


def format_gift_message(marketplace: str, name: str, model: str, price: float, 
                       floor_price: float, model_floor: Optional[float], 
                       gift_floor: Optional[float], model_rarity: str, 
                       gift_number: str, model_sales: List[Dict], 
                       gift_id: str, has_inscription: bool = False) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Унифицированное форматирование сообщения о подарке для всех маркетплейсов
    Формат как в примере: ✔️ ЛИСТИНГ\nSwiss Watch #23002 (https://t.me/nft/SwissWatch-23002) на Portals (https://t.me/portals/market?startapp=gift_...) за 69.99 TON
    
    Returns:
        tuple: (caption, keyboard)
    """
    from datetime import datetime, timedelta
    
    marketplace_names = {
        'portals': 'Portals',
        'tonnel': 'Tonnel',
        'mrkt': 'MRKT'
    }
    marketplace_name = marketplace_names.get(marketplace, marketplace)
    
    # Формируем ссылку на подарок в формате Telegram NFT: https://t.me/nft/Name-Number
    clean_name = re.sub(r'[^\w\s-]', '', str(name)).strip()
    clean_name = re.sub(r'\s+', '', clean_name)  # Убираем все пробелы
    if clean_name and gift_number and gift_number != 'N/A':
        gift_nft_url = f"https://t.me/nft/{clean_name}-{gift_number}"
    else:
        gift_nft_url = ""
    
    # Формируем ссылку на маркетплейс
    marketplace_url = ""
    if marketplace == 'portals' and gift_id and str(gift_id) != 'None':
        marketplace_url = f"https://t.me/portals/market?startapp=gift_{gift_id}"
    elif marketplace == 'tonnel' and gift_id and str(gift_id) != 'None':
        marketplace_url = f"https://t.me/tonnel_network_bot/gift?startapp={gift_id}"
    elif marketplace == 'mrkt' and gift_id and str(gift_id) != 'None':
        # Для MRKT gift_id должен быть хешем (32 символа hex)
        gift_id_str = str(gift_id).replace('-', '')
        if len(gift_id_str) == 32 and all(c in '0123456789abcdefABCDEF' for c in gift_id_str):
            marketplace_url = f"https://t.me/mrkt/app?startapp={gift_id_str}"
    
    # Формируем основную строку листинга с гиперссылками
    # Формат: Swiss Watch #23002 (https://t.me/nft/SwissWatch-23002) на Portals (https://t.me/portals/market?startapp=gift_...) за 69.99 TON
    gift_name_with_number = f"{name} #{gift_number}".strip()
    listing_line = f"✔️ ЛИСТИНГ\n"
    
    # Текст - гиперссылка (без дублирования ссылок в скобках)
    if gift_nft_url:
        listing_line += f"<a href='{gift_nft_url}'>{gift_name_with_number}</a>"
    else:
        listing_line += gift_name_with_number
    
    # Маркетплейс с гиперссылкой (без дублирования ссылок в скобках)
    if marketplace_url and marketplace_url != "#" and "startapp=None" not in marketplace_url:
        listing_line += f" на <a href='{marketplace_url}'>{marketplace_name}</a>"
    else:
        listing_line += f" на {marketplace_name}"
    
    listing_line += f" за {price:.2f} TON"
    
    # Формируем информацию о модели и фоне
    model_info = ""
    if model and model != 'N/A':
        model_info += f"Модель: {model}\n"
    
    # Формируем информацию о флорах
    floor_info = ""
    if gift_floor is not None:
        if isinstance(gift_floor, (int, float)) and gift_floor > 0:
            floor_info += f"Флор гифта: {gift_floor:.2f} TON\n"
        elif gift_floor and not isinstance(gift_floor, (int, float)):
            floor_info += f"Флор гифта: {gift_floor} TON\n"
    
    if model_floor is not None and model != 'N/A':
        if isinstance(model_floor, (int, float)) and model_floor > 0:
            floor_info += f"Флор модели: {model_floor:.2f} TON\n"
        elif model_floor and not isinstance(model_floor, (int, float)):
            floor_info += f"Флор модели: {model_floor} TON\n"
    
    # Убираем лишние ссылки - они уже в основном тексте
    
    # Формируем историю продаж в формате цитаты
    sales_text = ""
    if model_sales and len(model_sales) > 0:
        sales_lines = []
        for sale in model_sales[:5]:  # Берем до 5 продаж
            sale_price = sale.get('price') or sale.get('amount') or sale.get('sale_price') or sale.get('sold_price') or 0
            if isinstance(sale_price, (int, float)):
                sale_price = f"{sale_price:.1f}"
            else:
                try:
                    sale_price = f"{float(sale_price):.1f}"
                except:
                    sale_price = str(sale_price)
            
            # Получаем номер подарка из продажи
            sale_number = sale.get('external_collection_number') or sale.get('gift_num') or sale.get('number') or sale.get('gift_number') or 'N/A'
            sale_name = sale.get('name') or sale.get('gift_name') or sale.get('collection_name') or name
            
            # Формируем ссылку на проданный подарок
            clean_sale_name = re.sub(r'[^\w\s-]', '', str(sale_name)).strip()
            clean_sale_name = re.sub(r'\s+', '', clean_sale_name)
            if clean_sale_name and sale_number and sale_number != 'N/A':
                sale_nft_url = f"https://t.me/nft/{clean_sale_name}-{sale_number}"
            else:
                sold_gift_id = sale.get('gift_id') or sale.get('nft_id') or sale.get('id') or gift_id
                if marketplace == 'portals':
                    sale_nft_url = f"https://t.me/portals/market?startapp=gift_{sold_gift_id}"
                elif marketplace == 'tonnel':
                    sale_nft_url = f"https://t.me/tonnel_network_bot/gift?startapp={sold_gift_id}"
                elif marketplace == 'mrkt':
                    mrkt_hash = sale.get('mrkt_hash') or sale.get('hash') or sale.get('token') or sold_gift_id
                    sale_nft_url = f"https://t.me/mrkt/app?startapp={mrkt_hash}"
                else:
                    sale_nft_url = ""
            
            # Определяем маркетплейс продажи
            sale_marketplace = sale.get('marketplace') or 'Tonnel'
            sale_marketplace_name = marketplace_names.get(sale_marketplace, sale_marketplace)
            
            # Форматируем дату с улучшенным отображением времени
            sale_date = sale.get('date') or sale.get('sold_at') or sale.get('created_at') or sale.get('timestamp')
            days_ago = "N/A"
            if sale_date:
                try:
                    if isinstance(sale_date, (int, float)):
                        # Если это timestamp в секундах или миллисекундах
                        if sale_date > 1e10:
                            sale_dt = datetime.fromtimestamp(sale_date / 1000)  # миллисекунды
                        else:
                            sale_dt = datetime.fromtimestamp(sale_date)  # секунды
                    elif isinstance(sale_date, str):
                        # Пробуем разные форматы
                        try:
                            sale_dt = datetime.fromisoformat(sale_date.replace('Z', '+00:00'))
                        except:
                            try:
                                sale_dt = datetime.strptime(sale_date, '%Y-%m-%dT%H:%M:%S')
                            except:
                                sale_dt = datetime.strptime(sale_date, '%Y-%m-%d %H:%M:%S')
                    else:
                        sale_dt = None
                    
                    if sale_dt:
                        now = datetime.now()
                        if sale_dt.tzinfo:
                            now = datetime.now(sale_dt.tzinfo)
                        delta = now - sale_dt
                        
                        total_seconds = int(delta.total_seconds())
                        hours = total_seconds // 3600
                        days = delta.days
                        
                        if days == 0:
                            if hours == 0:
                                minutes = total_seconds // 60
                                if minutes == 0:
                                    days_ago = "только что"
                                elif minutes == 1:
                                    days_ago = "1 минуту назад"
                                elif minutes < 5:
                                    days_ago = f"{minutes} минуты назад"
                                else:
                                    days_ago = f"{minutes} минут назад"
                            elif hours == 1:
                                days_ago = "1 час назад"
                            elif hours < 24:
                                days_ago = f"{hours} часов назад"
                            else:
                                days_ago = "сегодня"
                        elif days == 1:
                            days_ago = "1 день назад"
                        elif days < 7:
                            days_ago = f"{days} дней назад"
                        else:
                            # Больше 7 дней - показываем полную дату без времени
                            days_ago = sale_dt.strftime("%d.%m.%Y")
                except Exception as e:
                    logger.debug(f"Error parsing sale date: {e}")
            
            # Формируем строку продажи: #23423 за 45.0 TON на Tonnel - 1 день назад
            # Текст - гиперссылка (без дублирования ссылок в скобках)
            if sale_nft_url:
                sale_line = f"<a href='{sale_nft_url}'>#{sale_number}</a>"
            else:
                sale_line = f"#{sale_number}"
            sale_line += f" за {sale_price} TON на {sale_marketplace_name} - {days_ago}"
            sales_lines.append(sale_line)
        
        if sales_lines:
            # История продаж в формате цитаты
            sales_text = "\n\n<blockquote>" + "\n".join(sales_lines) + "</blockquote>"
    
    # Формируем полное сообщение
    caption = listing_line
    if model_info:
        caption += "\n" + model_info.strip()
    if floor_info:
        caption += "\n\n" + floor_info.strip()
    if sales_text:
        caption += sales_text
    
    # Создаем только одну кнопку "Открыть на [маркетплейс]"
    if marketplace_url:
        button_text = f"Открыть на {marketplace_name}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button_text, url=marketplace_url)]
        ])
    else:
        keyboard = None
    
    return caption, keyboard


async def process_new_gifts(items, marketplace: str):
    """Обработка новых подарков для конкретного маркетплейса"""
    global auth_token
    
    if isinstance(items, str):
        logger.error(f"API error in check_new_gifts ({marketplace}): {items}")
        if marketplace == 'portals' and "auth" in items.lower():
            auth_token = await init_auth()
        return

    if not isinstance(items, list) or not items:
        return

    # Получаем список уже уведомленных подарков (с учетом маркетплейса)
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT gift_id FROM notified_gifts")
                notified_ids = {row[0] for row in await cur.fetchall()}

            # Проверяем каждый подарок
            for item in items:
                # Получаем ID подарка
                gift_id = None
                if isinstance(item, dict):
                    gift_id = item.get('id') or item.get('gift_id') or item.get('nft_id')
                elif hasattr(item, 'id'):
                    gift_id = item.id
                
                if not gift_id:
                    continue
                
                # Преобразуем ID в строку с префиксом маркетплейса для уникальности
                gift_id_str = f"{marketplace}_{gift_id}"
                gift_id_original = str(gift_id)  # Оригинальный ID для API запросов
                
                # Проверяем, был ли уже уведомлен
                if gift_id_str in notified_ids:
                    continue
                
                # Получаем детальную информацию о подарке в зависимости от маркетплейса
                gift_details = None
                sales = []
                
                if marketplace == 'portals':
                    # Используем токен из config, если он задан, иначе используем auth_token
                    portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                    if not portals_auth:
                        logger.warning("No Portals auth token available, skipping gift details")
                        continue
                    
                    if inspect.iscoroutinefunction(search_by_id):
                        gift_details = await search_by_id(gift_id_original, portals_auth)
                    else:
                        gift_details = await asyncio.to_thread(search_by_id, gift_id_original, portals_auth)
                    
                    # Отключаем загрузку последних продаж (шум/429)
                    sales = []
                    
                    logger.debug(f"Portals gift_details for {gift_id_original}: {type(gift_details)}, keys: {list(gift_details.keys()) if isinstance(gift_details, dict) else 'N/A'}")
                    # Детальное логирование структуры данных для отладки
                    if isinstance(gift_details, dict):
                        import json
                        logger.info(f"Portals gift_details structure: {json.dumps({k: str(type(v).__name__) + (' (dict keys: ' + str(list(v.keys())[:5]) + '...)' if isinstance(v, dict) else '') for k, v in list(gift_details.items())[:10]}, indent=2, ensure_ascii=False)}")
                        # Проверяем наличие полей редкости
                        rarity_fields = ['model_rarity', 'rarity', 'model_rarity_name', 'rarity_name', 'model_rarity_percent', 'rarity_percent']
                        found_rarity = {k: gift_details.get(k) for k in rarity_fields if k in gift_details}
                        if found_rarity:
                            logger.info(f"Found rarity fields in gift_details: {found_rarity}")
                        else:
                            logger.warning(f"No rarity fields found in gift_details. Available keys: {list(gift_details.keys())}")
                elif marketplace == 'tonnel':
                    if get_tonnel_gift_by_id:
                        gift_details = get_tonnel_gift_by_id(gift_id_original, TONNEL_AUTH)
                    # Для Tonnel продажи получаем через модель (будет получено позже)
                elif marketplace == 'mrkt':
                    if not MRKT_AUTH:
                        logger.warning("MRKT_AUTH not configured, skipping gift details")
                    elif get_mrkt_gift_by_id:
                        gift_details = get_mrkt_gift_by_id(gift_id_original, MRKT_AUTH)
                    # Для MRKT продажи получаем через модель (будет получено позже)
                
                # Формируем данные о подарке - сначала из item (который приходит из search()), потом из gift_details
                # В item уже есть все нужные данные: name, model, price, floor_price, model_rarity, photo_url и т.д.
                gift_data = {}
                if isinstance(item, dict):
                    gift_data.update(item)
                elif hasattr(item, '__dict__'):
                    gift_data.update(item.__dict__)
                elif hasattr(item, 'name'):
                    # Если это объект с атрибутами
                    gift_data = {
                        'name': getattr(item, 'name', None),
                        'model': getattr(item, 'model', None),
                        'price': getattr(item, 'price', 0),
                        'floor_price': getattr(item, 'floor_price', None),
                        'model_rarity': getattr(item, 'model_rarity', None),
                        'photo_url': getattr(item, 'photo_url', None),
                        'id': getattr(item, 'id', None),
                        'external_collection_number': getattr(item, 'external_collection_number', None),
                    }
                
                # Дополняем данными из gift_details если они есть (приоритет gift_details)
                if gift_details and isinstance(gift_details, dict):
                    gift_data.update(gift_details)
                
                # Для MRKT извлекаем хеш для ссылки (должен быть в формате 32 символа hex)
                if marketplace == 'mrkt':
                    # Проверяем, является ли id уже хешем
                    def is_hex_hash(value):
                        if not value:
                            return False
                        value_str = str(value).replace('-', '')
                        return len(value_str) == 32 and all(c in '0123456789abcdefABCDEF' for c in value_str)
                    
                    # Сначала пробуем mrkt_hash из преобразованных данных
                    mrkt_hash = gift_data.get('mrkt_hash')
                    if mrkt_hash:
                        mrkt_hash = str(mrkt_hash).replace('-', '')
                    elif is_hex_hash(gift_id_original):
                        # Если gift_id_original уже хеш, используем его
                        mrkt_hash = str(gift_id_original).replace('-', '')
                    else:
                        # Ищем хеш в других полях
                        mrkt_hash = (
                            gift_data.get('hash') or 
                            gift_data.get('hash_id') or 
                            gift_data.get('token') or 
                            gift_data.get('uuid') or
                            gift_data.get('app_id') or
                            gift_data.get('startapp_id') or
                            None
                        )
                        if mrkt_hash:
                            mrkt_hash = str(mrkt_hash).replace('-', '')
                        else:
                            # Fallback на обычный ID (может быть не хеш, но попробуем)
                            mrkt_hash = str(gift_id_original)
                    
                    # Обновляем gift_id_original для использования в ссылке
                    gift_id_original = mrkt_hash
                    logger.info(f"MRKT gift hash: original_id={gift_id}, extracted_hash={mrkt_hash}, final_id={gift_id_original}")
                
                # Извлекаем информацию напрямую из gift_data (который содержит данные из item и gift_details)
                name = gift_data.get('name') or gift_data.get('collection_name') or 'Unknown'
                model = gift_data.get('model') or gift_data.get('model_name') or gift_data.get('variant') or gift_data.get('variant_name') or 'N/A'
                
                # Логируем для отладки извлечения модели
                if model == 'N/A':
                    logger.warning(f"Model is N/A for gift {gift_id_original}. gift_data keys: {list(gift_data.keys()) if isinstance(gift_data, dict) else 'N/A'}")
                    # Пробуем получить из вложенных объектов
                    if isinstance(gift_data, dict):
                        for key in ['model_data', 'metadata', 'attributes', 'properties', 'model', 'collection', 'variant']:
                            nested = gift_data.get(key)
                            if isinstance(nested, dict):
                                model = nested.get('model') or nested.get('model_name') or nested.get('variant') or nested.get('variant_name') or model
                                if model != 'N/A':
                                    logger.info(f"Found model in nested {key}: {model}")
                                    break
                
                price = float(gift_data.get('price', 0)) if gift_data.get('price') else 0
                floor_price = float(gift_data.get('floor_price', 0)) if gift_data.get('floor_price') else 0
                photo_url = gift_data.get('photo_url') or gift_data.get('image_url') or gift_data.get('image')
                
                # Получаем номер подарка
                gift_number = (
                    gift_data.get('external_collection_number') or 
                    gift_data.get('gift_num') or 
                    gift_data.get('number') or
                    gift_data.get('gift_number') or
                    'N/A'
                )
                
                # Получаем редкость модели - приоритет из item (который приходит из search())
                model_rarity = (
                    gift_data.get('model_rarity') or 
                    gift_data.get('rarity') or 
                    gift_data.get('model_rarity_name') or
                    gift_data.get('rarity_name') or
                    gift_data.get('model_rarity_percent') or
                    gift_data.get('rarity_percent') or
                    'N/A'
                )
                
                # Логируем для отладки - что пришло из item
                if isinstance(item, dict):
                    logger.info(f"Item data for {gift_id_original}: name={item.get('name')}, model={item.get('model')}, model_rarity={item.get('model_rarity')}, floor_price={item.get('floor_price')}")
                
                # Если редкость все еще N/A, пробуем получить из вложенных объектов
                if model_rarity == 'N/A' and isinstance(gift_data, dict):
                    # Проверяем вложенные объекты
                    for key in ['model_data', 'metadata', 'attributes', 'properties', 'model', 'collection', 'model_info', 'collection_info']:
                        nested = gift_data.get(key)
                        if isinstance(nested, dict):
                            model_rarity = (
                                nested.get('model_rarity') or 
                                nested.get('rarity') or 
                                nested.get('model_rarity_name') or
                                nested.get('rarity_name') or
                                nested.get('model_rarity_percent') or
                                nested.get('rarity_percent') or
                                nested.get('rarity_tier') or
                                nested.get('tier') or
                                model_rarity
                            )
                            if model_rarity != 'N/A':
                                logger.info(f"Found model_rarity in nested {key}: {model_rarity}")
                                break
                    
                    # Если все еще N/A, проверяем все ключи, содержащие "rarity" или "tier"
                    if model_rarity == 'N/A':
                        for key, value in gift_data.items():
                            if ('rarity' in key.lower() or 'tier' in key.lower()) and value and value != 'N/A':
                                model_rarity = str(value)
                                logger.info(f"Found model_rarity in key '{key}': {model_rarity}")
                                break
                
                # Логируем для отладки
                logger.info(f"Final extracted model_rarity: {model_rarity} for {name} / {model}")
                if model_rarity == 'N/A':
                    logger.warning(f"Could not extract model_rarity for {name} / {model}. gift_data keys: {list(gift_data.keys())[:30] if isinstance(gift_data, dict) else 'N/A'}")
                
                # Получаем флор модели и флор подарка в зависимости от маркетплейса
                model_floor = None
                gift_floor = None
                model_sales = []
                
                if marketplace == 'portals':
                    # Используем токен из config, если он задан, иначе используем auth_token
                    portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                    if not portals_auth:
                        logger.warning("No Portals auth token available, skipping floor prices and sales")
                    else:
                        if name != 'Unknown' and model and model != 'N/A':
                            try:
                                logger.info(f"Getting floor prices for {name} / {model} (Portals)")
                                if inspect.iscoroutinefunction(get_model_floor_price):
                                    model_floor = await get_model_floor_price(name, model, portals_auth)
                                else:
                                    model_floor = await asyncio.to_thread(get_model_floor_price, name, model, portals_auth)
                                logger.info(f"Model floor result: {model_floor} (type: {type(model_floor)})")
                                if model_floor is None:
                                    logger.warning(f"Model floor is None for {name} / {model}")
                            except Exception as e:
                                error_msg = str(e)
                                if "Could not resolve host" in error_msg or "DNS" in error_msg:
                                    logger.warning(f"Network error getting model floor price (DNS/host resolution): {error_msg}")
                                else:
                                    logger.error(f"Error getting model floor price: {e}", exc_info=True)
                        
                        if name != 'Unknown':
                            try:
                                if inspect.iscoroutinefunction(get_gift_floor_price):
                                    gift_floor = await get_gift_floor_price(name, portals_auth)
                                else:
                                    gift_floor = await asyncio.to_thread(get_gift_floor_price, name, portals_auth)
                                logger.info(f"Gift floor result: {gift_floor} (type: {type(gift_floor)})")
                                if gift_floor is None:
                                    logger.warning(f"Gift floor is None for {name}")
                            except Exception as e:
                                error_msg = str(e)
                                if "Could not resolve host" in error_msg or "DNS" in error_msg:
                                    logger.warning(f"Network error getting gift floor price (DNS/host resolution): {error_msg}")
                                else:
                                    logger.error(f"Error getting gift floor price: {e}", exc_info=True)
                        
                        # Получаем историю продаж модели с Tonnel для любого подарка
                        if name != 'Unknown' and model and model != 'N/A' and get_tonnel_model_sales_history and TONNEL_AUTH:
                            try:
                                logger.info(f"Getting model sales history from Tonnel for {name} / {model}")
                                model_sales = get_tonnel_model_sales_history(name, model, TONNEL_AUTH, limit=5)
                            except Exception as e:
                                logger.error(f"Error getting Tonnel model sales history: {e}")
                                model_sales = []
                        else:
                            model_sales = []
                            
                elif marketplace == 'tonnel':
                    if name != 'Unknown' and model and model != 'N/A' and get_tonnel_model_floor_price:
                        try:
                            logger.info(f"Getting floor prices for {name} / {model} (Tonnel)")
                            model_floor = get_tonnel_model_floor_price(name, model, TONNEL_AUTH)
                            logger.info(f"Model floor: {model_floor}")
                        except Exception as e:
                            logger.error(f"Error getting Tonnel model floor price: {e}")
                    
                    if name != 'Unknown' and get_tonnel_gift_floor_price:
                        try:
                            gift_floor = get_tonnel_gift_floor_price(name, TONNEL_AUTH)
                            logger.info(f"Gift floor: {gift_floor}")
                        except Exception as e:
                            logger.error(f"Error getting Tonnel gift floor price: {e}")
                    
                    # Получаем историю продаж модели с Tonnel
                    if name != 'Unknown' and model and model != 'N/A' and get_tonnel_model_sales_history and TONNEL_AUTH:
                        try:
                            logger.info(f"Getting model sales history from Tonnel for {name} / {model}")
                            model_sales = get_tonnel_model_sales_history(name, model, TONNEL_AUTH, limit=5)
                        except Exception as e:
                            logger.error(f"Error getting Tonnel model sales history: {e}")
                            model_sales = []
                    else:
                        model_sales = []
                
                elif marketplace == 'mrkt':
                    if not MRKT_AUTH:
                        logger.warning("MRKT_AUTH not configured, skipping floor prices and sales")
                    else:
                        # Добавляем задержку для избежания rate limiting
                        await asyncio.sleep(0.2)  # Оптимизировано
                        
                        if name != 'Unknown' and model and model != 'N/A' and get_mrkt_model_floor_price:
                            try:
                                logger.info(f"Getting floor prices for {name} / {model} (MRKT)")
                                model_floor = get_mrkt_model_floor_price(name, model, MRKT_AUTH)
                                logger.info(f"Model floor: {model_floor}")
                            except Exception as e:
                                error_msg = str(e)
                                if "429" in error_msg or "Too Many Requests" in error_msg:
                                    logger.warning(f"Rate limit (429) getting MRKT model floor price, waiting...")
                                    await asyncio.sleep(0.3)  # Оптимизировано  # Оптимизировано
                                else:
                                    logger.error(f"Error getting MRKT model floor price: {e}")
                        
                        # Добавляем задержку между запросами
                        await asyncio.sleep(0.2)  # Оптимизировано
                        
                        if name != 'Unknown' and get_mrkt_gift_floor_price:
                            try:
                                gift_floor = get_mrkt_gift_floor_price(name, MRKT_AUTH)
                                logger.info(f"Gift floor: {gift_floor}")
                            except Exception as e:
                                error_msg = str(e)
                                if "429" in error_msg or "Too Many Requests" in error_msg:
                                    logger.warning(f"Rate limit (429) getting MRKT gift floor price, waiting...")
                                    await asyncio.sleep(0.3)  # Оптимизировано  # Оптимизировано
                                else:
                                    logger.error(f"Error getting MRKT gift floor price: {e}")
                        
                        # Получаем историю продаж модели с Tonnel для любого подарка
                        if name != 'Unknown' and model and model != 'N/A' and get_tonnel_model_sales_history and TONNEL_AUTH:
                            try:
                                logger.info(f"Getting model sales history from Tonnel for {name} / {model}")
                                model_sales = get_tonnel_model_sales_history(name, model, TONNEL_AUTH, limit=5)
                            except Exception as e:
                                logger.error(f"Error getting Tonnel model sales history: {e}")
                                model_sales = []
                        else:
                            model_sales = []
                
                # Проверяем наличие подписи (inscription/signature)
                has_inscription = False
                inscription_fields = ['inscription', 'signature', 'signed', 'has_inscription', 'has_signature']
                for field in inscription_fields:
                    if gift_data.get(field):
                        has_inscription = bool(gift_data.get(field))
                        break
                    if isinstance(item, dict) and item.get(field):
                        has_inscription = bool(item.get(field))
                        break
                
                # Используем унифицированную функцию форматирования
                caption, keyboard = format_gift_message(
                    marketplace=marketplace,
                    name=name,
                    model=model,
                    price=float(price) if price else 0,
                    floor_price=float(floor_price) if floor_price else 0,
                    model_floor=model_floor,
                    gift_floor=gift_floor,
                    model_rarity=model_rarity,
                    gift_number=str(gift_number),
                    model_sales=model_sales,
                    gift_id=gift_id_original,
                    has_inscription=has_inscription
                )
                
                # Отправляем уведомление пользователям бота с учетом выбранного маркетплейса
                async with db_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        # Получаем пользователей с включенными уведомлениями и правильным выбором маркетплейса
                        try:
                            # Получаем пользователей, которые выбрали этот маркетплейс или "both"
                            await cur.execute("""
                                SELECT DISTINCT bu.user_id 
                                FROM bot_users bu
                                WHERE (bu.notifications_enabled IS NULL OR bu.notifications_enabled = TRUE)
                                AND (
                                    bu.marketplace = %s 
                                    OR bu.marketplace = 'all'
                                    OR bu.marketplace IS NULL
                                )
                                
                                UNION
                                
                                SELECT DISTINCT g.user_id 
                                FROM gifts g
                                JOIN bot_users bu ON g.user_id = bu.user_id
                                WHERE (bu.notifications_enabled IS NULL OR bu.notifications_enabled = TRUE)
                                AND (
                                    bu.marketplace = %s 
                                    OR bu.marketplace = 'all'
                                    OR bu.marketplace IS NULL
                                )
                            """, (marketplace, marketplace))
                            users = await cur.fetchall()
                            logger.info(f"Found {len(users)} users with enabled notifications for {marketplace}")
                        except Exception as e:
                            # Если колонка не существует или ошибка, проверяем другим способом
                            logger.warning(f"Error checking marketplace/notifications, trying alternative: {e}")
                            try:
                                # Получаем всех пользователей с уведомлениями
                                await cur.execute("""
                                    SELECT DISTINCT user_id 
                                    FROM bot_users 
                                    WHERE notifications_enabled IS NULL OR notifications_enabled = TRUE
                                """)
                                users = await cur.fetchall()
                                logger.info(f"Found {len(users)} users with enabled notifications (fallback)")
                            except Exception as e2:
                                # Если и это не работает, получаем всех пользователей
                                logger.error(f"Fallback also failed: {e2}")
                                await cur.execute("""
                                    SELECT DISTINCT user_id FROM bot_users
                                """)
                                users = await cur.fetchall()
                                logger.warning(f"Using all users as fallback: {len(users)} users")
                        
                        if not users:
                            logger.info(f"No users to notify for new gift {gift_id_str}")
                        else:
                            # Отправляем уведомление каждому пользователю
                            notified_count = 0
                            for (user_id,) in users:
                                try:
                                    if photo_url:
                                        await bot.send_photo(
                                            chat_id=user_id,
                                            photo=photo_url,
                                            caption=caption,
                                            reply_markup=keyboard,
                                            parse_mode="HTML"
                                        )
                                    else:
                                        await bot.send_message(
                                            chat_id=user_id,
                                            text=caption,
                                            reply_markup=keyboard,
                                            parse_mode="HTML"
                                        )
                                    notified_count += 1
                                except Exception as e:
                                    logger.error(f"Error sending new gift notification to user {user_id}: {e}")
                            
                            logger.info(f"Notified {notified_count} users about new gift {gift_id_str}")
                        
                        # Отмечаем подарок как уведомленный
                        await cur.execute(
                            "INSERT IGNORE INTO notified_gifts (gift_id) VALUES (%s)",
                            (gift_id_str,)
                        )
                        await conn.commit()
                
                logger.info(f"New gift notified: {name} ({model}) - ID: {gift_id_str}")
            
    except Exception as e:
        logger.error(f"Error in check_new_gifts: {e}", exc_info=True)


async def price_tracker():
    """Фоновая задача для отслеживания цен"""
    while True:
        try:
            await check_prices()
        except Exception as e:
            logger.error(f"Error in price_tracker: {e}", exc_info=True)
        await asyncio.sleep(30)  # Оптимизировано: проверка каждые 30 секунд


async def new_gifts_tracker():
    """Фоновая задача для отслеживания новых подарков"""
    while True:
        try:
            await check_new_gifts()
        except Exception as e:
            logger.error(f"Error in new_gifts_tracker: {e}", exc_info=True)
        await asyncio.sleep(2)  # Проверка каждые 2 секунды


async def init_existing_gifts():
    """Инициализация существующих подарков при запуске - чтобы не отправлять старые"""
    global new_gifts_last_ids
    
    logger.info("Initializing existing gifts to avoid sending old ones...")
    
    # Инициализируем словари для каждого маркетплейса
    for mp in ['portals', 'tonnel', 'mrkt']:
        if mp not in new_gifts_last_ids:
            new_gifts_last_ids[mp] = set()
    
    # Загружаем текущие подарки из каждого маркетплейса
    for marketplace in ['portals', 'tonnel', 'mrkt']:
        try:
            items = []
            if marketplace == 'portals':
                portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                if portals_auth:
                    logger.info(f"[init] Loading existing gifts from portals...")
                    if inspect.iscoroutinefunction(search):
                        items = await search(limit=999, sort="latest", authData=portals_auth)
                    else:
                        items = await asyncio.to_thread(search, limit=999, sort="latest", authData=portals_auth)
            elif marketplace == 'tonnel' and search_tonnel:
                logger.info(f"[init] Loading existing gifts from tonnel...")
                items = search_tonnel(limit=30, sort="latest", authData=TONNEL_AUTH)
            elif marketplace == 'mrkt' and search_mrkt and MRKT_AUTH:
                logger.info(f"[init] Loading existing gifts from mrkt...")
                items = search_mrkt(limit=999, sort="price_asc", auth_token=MRKT_AUTH)
            
            # Приводим формат к списку
            if isinstance(items, dict):
                if 'results' in items:
                    items = items.get('results') or []
                elif 'items' in items:
                    items = items.get('items') or []
                elif 'gifts' in items:
                    items = items.get('gifts') or []
                elif 'data' in items and isinstance(items['data'], list):
                    items = items['data']
                else:
                    items = []
            
            if isinstance(items, list):
                count = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    
                    gift_id = None
                    if marketplace == 'portals':
                        # Portals использует разные поля для ID - проверяем все возможные варианты
                        gift_id = (item.get('id') or item.get('gift_id') or item.get('nft_id') or 
                                  item.get('giftId') or item.get('_id') or item.get('gift_id'))
                        # Если ID - это число, конвертируем в строку для единообразия
                        if gift_id is not None:
                            gift_id = str(gift_id)
                    elif marketplace == 'tonnel':
                        gift_id = item.get('gift_id') or item.get('id')
                        if gift_id is not None:
                            gift_id = str(gift_id)
                    elif marketplace == 'mrkt':
                        gift_id = item.get('id') or item.get('mrkt_hash') or item.get('giftId') or item.get('giftIdString')
                        if gift_id is not None:
                            gift_id = str(gift_id)
                    
                    if gift_id:
                        gift_id_str = f"{marketplace}_{gift_id}"
                        new_gifts_last_ids[marketplace].add(gift_id_str)
                        count += 1
                
                logger.info(f"[init] Loaded {count} existing gifts from {marketplace}")
        except Exception as e:
            logger.error(f"Error initializing existing gifts from {marketplace}: {e}")
    
    logger.info("Finished initializing existing gifts")


async def new_gifts_monitoring_tracker():
    """Фоновая задача для мониторинга новых подарков каждую секунду для пользователей с включенным мониторингом и админа"""
    global new_gifts_last_ids
    
    logger.info("Starting new_gifts_monitoring_tracker")
    
    # Инициализируем словари для каждого маркетплейса
    for mp in ['portals', 'tonnel', 'mrkt']:
        if mp not in new_gifts_last_ids:
            new_gifts_last_ids[mp] = set()
    
    while True:
        try:
            if not db_pool:
                await asyncio.sleep(0.3)  # Оптимизировано
                continue
            
            # Получаем пользователей с включенным мониторингом (включая админа, если у него включен мониторинг)
            users_to_notify = []
            
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT user_id FROM new_gifts_monitoring WHERE enabled = TRUE
                    """)
                    monitoring_users = await cur.fetchall()
                    for (user_id,) in monitoring_users:
                        users_to_notify.append(user_id)
            
            if not users_to_notify:
                await asyncio.sleep(1)
                continue
            
            # Получаем список маркетплейсов для проверки и кэшируем настройки пользователей
            # Объединяем все маркетплейсы, которые включены хотя бы у одного пользователя с включенным мониторингом
            marketplaces_to_check = set()
            marketplace_users_cache = {}  # Кэш: {marketplace: set(user_ids)}
            
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Получаем все уникальные маркетплейсы и пользователей с включенным мониторингом
                    await cur.execute("""
                        SELECT DISTINCT um.marketplace, um.user_id
                        FROM user_marketplaces um
                        INNER JOIN new_gifts_monitoring ngm ON um.user_id = ngm.user_id
                        WHERE um.enabled = TRUE AND ngm.enabled = TRUE
                    """)
                    results = await cur.fetchall()
                    for (mp, user_id) in results:
                        # Фильтруем только разрешенные маркетплейсы (исключаем getgems и другие)
                        if mp in ['portals', 'tonnel', 'mrkt']:
                            marketplaces_to_check.add(mp)
                            if mp not in marketplace_users_cache:
                                marketplace_users_cache[mp] = set()
                            marketplace_users_cache[mp].add(user_id)
            
            # Если нет маркетплейсов для проверки, пропускаем
            if not marketplaces_to_check:
                await asyncio.sleep(0.3)  # Оптимизировано
                continue
            
            # Обрабатываем все маркетплейсы параллельно
            async def process_marketplace(marketplace):
                """Обработка одного маркетплейса"""
                try:
                    # Пропускаем неразрешенные маркетплейсы (например, getgems)
                    if marketplace not in ['portals', 'tonnel', 'mrkt']:
                        logger.warning(f"[monitor] Skipping unsupported marketplace: {marketplace}")
                        return
                    
                    logger.info(f"[monitor] Processing marketplace: {marketplace}")
                    # Убрана задержка для ускорения парсинга
                    
                    # Получаем новые подарки
                    items = []
                    if marketplace == 'portals':
                        logger.info(f"[monitor] Starting Portals processing...")
                        portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                        if not portals_auth:
                            logger.warning(f"[monitor] Portals auth token not available, skipping")
                            return
                        
                        logger.info(f"[monitor] Portals auth token available, starting search...")
                        # Получаем только первую страницу (самые новые подарки) для быстрого обновления
                        max_retries = 3
                        retry_delay = 1
                        items = []
                        
                        for attempt in range(max_retries):
                            try:
                                # Используем API напрямую для получения последних подарков
                                from urllib.parse import quote_plus
                                import requests as req_lib
                                try:
                                    from curl_cffi import requests as curl_requests
                                    requests_lib = curl_requests
                                except ImportError:
                                    requests_lib = req_lib
                                
                                from portalsmp import PORTALS_API_URL
                                # Получаем только первую страницу (offset=0) с максимальным лимитом для последних подарков
                                url = f"{PORTALS_API_URL}nfts/search?offset=0&limit=50&sort_by=listed_at+desc&status=listed&exclude_bundled=true&premarket_status=all"
                                
                                headers = {
                                    "Authorization": portals_auth if portals_auth.startswith('tma ') else f"tma {portals_auth}",
                                    "Accept": "application/json, text/plain, */*",
                                    "Origin": "https://portal-market.com",
                                    "Referer": "https://portal-market.com/",
                                }
                                
                                if hasattr(requests_lib, 'Session') and hasattr(requests_lib.Session, 'impersonate'):
                                    session = requests_lib.Session(impersonate="chrome110")
                                    response = session.get(url, headers=headers, timeout=15)
                                else:
                                    response = requests_lib.get(url, headers=headers, timeout=15)
                                
                                if response.status_code == 429:
                                    if attempt < max_retries - 1:
                                        logger.warning(f"Portals rate limit, waiting {retry_delay * (attempt + 1)}s...")
                                        await asyncio.sleep(retry_delay * (attempt + 1))
                                        continue
                                    else:
                                        logger.error("Portals rate limit exceeded")
                                        break
                                
                                response.raise_for_status()
                                data = response.json()
                                
                                page_items = data.get('results') or data.get('items') or []
                                
                                if not page_items:
                                    logger.warning(f"[monitor] Portals returned no items")
                                    break
                                
                                # Конвертируем в словари если нужно
                                converted_items = []
                                for item in page_items:
                                    if isinstance(item, dict):
                                        converted_items.append(item)
                                    elif hasattr(item, '__dict__'):
                                        converted_items.append(item.__dict__)
                                    elif hasattr(item, 'id') or hasattr(item, 'tg_id'):
                                        item_dict = {}
                                        for attr in ['id', 'tg_id', 'gift_id', 'nft_id', 'giftId', '_id', 
                                                    'name', 'collectionName', 'gift_name', 'model', 'modelName', 
                                                    'model_name', 'price', 'floor_price', 'photo_url', 
                                                    'external_collection_number', 'number', 'giftNumber', 
                                                    'model_rarity', 'rarity', 'attributes']:
                                            if hasattr(item, attr):
                                                item_dict[attr] = getattr(item, attr)
                                        if item_dict:
                                            converted_items.append(item_dict)
                                
                                items = converted_items
                                logger.info(f"[monitor] Portals returned {len(items)} items (latest page), processing...")
                                break  # Успешно получили данные
                                
                            except Exception as e:
                                error_str = str(e)
                                if "429" in error_str or "too many requests" in error_str.lower():
                                    if attempt < max_retries - 1:
                                        logger.warning(f"Portals 429 error, retrying in {retry_delay * (attempt + 1)} seconds...")
                                        await asyncio.sleep(retry_delay * (attempt + 1))
                                        continue
                                logger.error(f"Error fetching Portals items: {e}", exc_info=True)
                                if attempt == max_retries - 1:
                                    items = []
                        
                        if not items:
                            logger.warning(f"[monitor] Portals returned no items after {max_retries} attempts")
                            return
                    elif marketplace == 'tonnel' and search_tonnel:
                        logger.info(f"[monitor] Starting Tonnel processing...")
                        try:
                            # Tonnel имеет лимит 30, используем максимальный лимит
                            items = search_tonnel(limit=30, sort="latest", authData=TONNEL_AUTH)
                            # Приводим формат к списку
                            if isinstance(items, dict):
                                if 'results' in items:
                                    items = items.get('results') or []
                                elif 'items' in items:
                                    items = items.get('items') or []
                                elif 'gifts' in items:
                                    items = items.get('gifts') or []
                                else:
                                    logger.warning(f"Invalid dict format for {marketplace}: keys={list(items.keys())}")
                                    items = []
                            elif isinstance(items, str):
                                logger.error(f"Tonnel returned error: {items}")
                                items = []
                            logger.info(f"[monitor] Tonnel returned {len(items) if isinstance(items, list) else 'non-list'} items")
                        except Exception as e:
                            logger.error(f"Error fetching Tonnel items: {e}", exc_info=True)
                            items = []
                    elif marketplace == 'mrkt' and search_mrkt and MRKT_AUTH:
                        logger.info(f"[monitor] Starting MRKT processing...")
                        try:
                            # MRKT имеет лимит 20, используем максимальный лимит
                            # Для MRKT используем сортировку по цене (price_asc), так как latest даёт 400 (ordering null)
                            items = search_mrkt(limit=20, sort="price_asc", auth_token=MRKT_AUTH)
                            # Приводим формат к списку
                            if isinstance(items, dict):
                                if 'gifts' in items:
                                    items = items.get('gifts') or []
                                elif 'results' in items:
                                    items = items.get('results') or []
                                elif 'items' in items:
                                    items = items.get('items') or []
                                else:
                                    logger.warning(f"Invalid dict format for {marketplace}: keys={list(items.keys())}")
                                    items = []
                            elif isinstance(items, str):
                                logger.error(f"MRKT returned error: {items}")
                                items = []
                            logger.info(f"[monitor] MRKT returned {len(items) if isinstance(items, list) else 'non-list'} items")
                        except Exception as e:
                            logger.error(f"Error fetching MRKT items: {e}", exc_info=True)
                            items = []
                    else:
                        logger.warning(f"[monitor] Marketplace {marketplace} not supported or missing dependencies")
                        return
                    
                    if isinstance(items, str):
                        logger.warning(f"Items is error string for {marketplace}: {items}")
                        return
                    
                    if not isinstance(items, list):
                        logger.warning(f"Invalid items format for {marketplace}: {type(items)}")
                        return
                    
                    # Убрано избыточное логирование
                    
                    if not items:
                        # Убрано избыточное логирование
                        return
                    
                    # Обрабатываем новые подарки (БЕЗ ЛИМИТОВ - все подарки)
                    processed_count = 0
                    new_count = 0
                    seen_count = 0
                    no_id_count = 0
                    not_dict_count = 0
                    
                    for item in items:
                        # Обрабатываем как словарь, так и объекты PortalsGift
                        item_dict = None
                        if isinstance(item, dict):
                            item_dict = item
                        elif hasattr(item, '__dict__'):
                            # Если это объект, преобразуем в словарь
                            item_dict = item.__dict__
                        elif hasattr(item, 'id') or hasattr(item, 'tg_id'):
                            # Если это объект с атрибутами, создаем словарь из атрибутов
                            item_dict = {}
                            for attr in ['id', 'tg_id', 'gift_id', 'nft_id', 'giftId', '_id', 
                                        'name', 'collectionName', 'gift_name', 'model', 'modelName', 
                                        'model_name', 'price', 'floor_price', 'photo_url', 
                                        'external_collection_number', 'number', 'giftNumber', 
                                        'model_rarity', 'rarity', 'attributes']:
                                if hasattr(item, attr):
                                    item_dict[attr] = getattr(item, attr)
                        
                        if not item_dict:
                            not_dict_count += 1
                            if not_dict_count <= 3:
                                logger.warning(f"[monitor] {marketplace} item cannot be converted to dict: type={type(item)}, value={str(item)[:100]}")
                            continue
                        
                        processed_count += 1
                        
                        # Получаем ID подарка
                        gift_id = None
                        if marketplace == 'portals':
                            # Portals использует разные поля для ID - проверяем все возможные варианты
                            gift_id = (item_dict.get('id') or item_dict.get('gift_id') or item_dict.get('nft_id') or 
                                      item_dict.get('giftId') or item_dict.get('_id') or item_dict.get('tg_id'))
                            # Если ID - это число, конвертируем в строку для единообразия
                            if gift_id is not None:
                                gift_id = str(gift_id)
                        elif marketplace == 'tonnel':
                            gift_id = item_dict.get('gift_id') or item_dict.get('id')
                            if gift_id is not None:
                                gift_id = str(gift_id)
                        elif marketplace == 'mrkt':
                            gift_id = item_dict.get('id') or item_dict.get('mrkt_hash') or item_dict.get('giftId') or item_dict.get('giftIdString')
                            if gift_id is not None:
                                gift_id = str(gift_id)
                        
                        if not gift_id:
                            no_id_count += 1
                            if no_id_count <= 3:  # Логируем только первые 3 для экономии места
                                logger.warning(f"Skipping item from {marketplace} - no ID found, keys: {list(item_dict.keys())[:20] if item_dict else 'N/A'}, item sample: {dict(list(item_dict.items())[:5]) if item_dict else {}}")
                            continue
                        
                        gift_id_str = f"{marketplace}_{gift_id}"
                        
                        # Получаем имя и модель для логирования
                        name = item_dict.get('name') or item_dict.get('collectionName') or item_dict.get('gift_name') or 'Unknown'
                        model = item_dict.get('model') or item_dict.get('modelName') or item_dict.get('model_name') or 'N/A'
                        
                        # Проверяем, новый ли это подарок
                        if gift_id_str not in new_gifts_last_ids[marketplace]:
                            # Это новый подарок - отправляем уведомления с ограничением параллелизма
                            new_gifts_last_ids[marketplace].add(gift_id_str)
                            new_count += 1
                            
                            # Используем кэш для фильтрации пользователей (уже получен выше)
                            filtered_users = list(marketplace_users_cache.get(marketplace, set()))
                            
                            # Отправляем все новые подарки параллельно (до 10 одновременно)
                            if filtered_users:
                                logger.info(f"[monitor] {marketplace}: ✅ NEW GIFT - {name} ({model}), ID: {gift_id}, sending to {len(filtered_users)} users")
                                # Создаем задачу для обработки этого подарка - все новые подарки будут отправлены
                                asyncio.create_task(process_new_gift_monitoring_with_semaphore(item_dict, marketplace, filtered_users))
                            else:
                                logger.debug(f"[monitor] {marketplace}: No users to notify for gift {name} ({model})")
                            
                            # Ограничиваем размер множества (храним последние 1000)
                            if len(new_gifts_last_ids[marketplace]) > 1000:
                                new_gifts_last_ids[marketplace] = set(list(new_gifts_last_ids[marketplace])[-1000:])
                        else:
                            seen_count += 1
                    
                    # Логируем статистику
                    if new_count > 0:
                        logger.info(f"[monitor] {marketplace.capitalize()}: ✅ {new_count} NEW GIFTS FOUND! {processed_count} processed, {seen_count} seen, {no_id_count} no ID")
                    elif no_id_count > 0 or not_dict_count > 0:
                        logger.warning(f"[monitor] {marketplace.capitalize()}: {new_count} new, {processed_count} processed, {seen_count} seen, {no_id_count} no ID, {not_dict_count} not dict")
                
                except Exception as e:
                    logger.error(f"[monitor] Error checking {marketplace} for monitoring: {e}", exc_info=True)
            
            # Запускаем обработку всех маркетплейсов параллельно
            logger.info(f"[monitor] Marketplaces to check: {sorted(marketplaces_to_check)}")
            tasks = [process_marketplace(mp) for mp in sorted(marketplaces_to_check)]
            if tasks:
                logger.info(f"[monitor] Starting {len(tasks)} marketplace tasks in parallel")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Проверяем результаты на исключения
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        marketplace_name = sorted(marketplaces_to_check)[i]
                        logger.error(f"[monitor] Exception in {marketplace_name} task: {result}", exc_info=result)
            else:
                logger.warning(f"[monitor] No tasks to run")
            
            # Небольшая задержка перед следующим циклом
            await asyncio.sleep(2)  # Проверка каждые 2 секунды
        
        except Exception as e:
            logger.error(f"Error in new_gifts_monitoring_tracker: {e}", exc_info=True)
            await asyncio.sleep(2)


async def process_new_gift_monitoring_with_semaphore(item: Dict, marketplace: str, users: List):
    """Обертка для process_new_gift_monitoring с ограничением параллелизма"""
    async with processing_semaphore:
        await process_new_gift_monitoring(item, marketplace, users)


async def should_process_gift_for_user(user_id: int, gift_name: str, model: str, price: float) -> bool:
    """Проверить, должен ли подарок быть обработан для пользователя"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Получаем выбранные подарки пользователя
                await cur.execute("""
                    SELECT name, model FROM gifts WHERE user_id = %s
                """, (user_id,))
                user_gifts = await cur.fetchall()
                
                if not user_gifts:
                    logger.debug(f"[filter] User {user_id} has no selected gifts, skipping")
                    return False  # У пользователя нет выбранных подарков
                
                # Нормализуем название и модель подарка для сравнения
                gift_name_normalized = re.sub(r"\s*\([^)]*\)", "", gift_name).strip().lower()
                model_normalized = re.sub(r"\s*\([^)]*\)", "", model).strip().lower() if model != 'N/A' else 'N/A'
                
                # Проверяем, подходит ли подарок под критерии пользователя
                for user_gift in user_gifts:
                    user_gift_name = user_gift['name']
                    user_model = user_gift['model']
                    
                    # Проверка подарка
                    gift_matches = False
                    if user_gift_name == "ANY":
                        gift_matches = True
                    else:
                        # Сравниваем названия (без учета регистра и редкости)
                        user_gift_clean = re.sub(r"\s*\([^)]*\)", "", user_gift_name).strip().lower()
                        gift_matches = user_gift_clean == gift_name_normalized
                    
                    # Проверка модели
                    model_matches = False
                    if user_model == "ANY":
                        model_matches = True
                    else:
                        # Сравниваем модели (без учета редкости)
                        user_model_clean = re.sub(r"\s*\([^)]*\)", "", user_model).strip().lower()
                        model_matches = user_model_clean == model_normalized
                    
                    # Если подарок и модель совпадают, проверяем фильтр цены
                    if gift_matches and model_matches:
                        # Получаем фильтр цены
                        await cur.execute("""
                            SELECT min_price, max_price FROM user_price_filters WHERE user_id = %s
                        """, (user_id,))
                        price_filter = await cur.fetchone()
                        
                        if price_filter:
                            min_price = price_filter.get('min_price')
                            max_price = price_filter.get('max_price')
                            
                            # Проверяем фильтр цены
                            if min_price is not None and price < min_price:
                                logger.debug(f"[filter] User {user_id}: price {price} < min_price {min_price}")
                                continue
                            if max_price is not None and price > max_price:
                                logger.debug(f"[filter] User {user_id}: price {price} > max_price {max_price}")
                                continue
                        
                        logger.debug(f"[filter] User {user_id}: Gift {gift_name} ({model}) matches filter {user_gift_name} ({user_model})")
                        return True  # Подарок подходит под все критерии
                
                logger.debug(f"[filter] User {user_id}: Gift {gift_name} ({model}) doesn't match any filters")
                return False  # Подарок не подходит ни под один критерий
                
    except Exception as e:
        logger.error(f"Error in should_process_gift_for_user: {e}", exc_info=True)
        return False

async def process_new_gift_monitoring(item: Dict, marketplace: str, users: List):
    """Обработка нового подарка для мониторинга с правильным форматом вывода"""
    try:
        
        # Извлекаем данные - для разных маркетплейсов поля могут отличаться
        if marketplace == 'portals':
            name = item.get('name') or item.get('collectionName') or item.get('gift_name') or 'Unknown'
        elif marketplace == 'tonnel':
            name = item.get('gift_name') or item.get('name') or item.get('collectionName') or 'Unknown'
        elif marketplace == 'mrkt':
            # Для MRKT используется collectionName или name (судя по логам)
            name = item.get('collectionName') or item.get('name') or item.get('gift_name') or 'Unknown'
        else:
            name = item.get('name') or item.get('collectionName') or item.get('gift_name') or 'Unknown'
        
        # Значения по умолчанию для предупреждений линтера
        gift_id_original = None
        photo_url = None
        floor_price = 0.0
        
        # Для разных маркетплейсов модель может быть в разных полях
        model = None
        if marketplace == 'portals':
            # Для Portals модель может быть в attributes
            model = item.get('model') or item.get('modelName') or item.get('model_name')
            if not model and 'attributes' in item and isinstance(item['attributes'], list):
                for attr in item['attributes']:
                    if isinstance(attr, dict) and attr.get('type') == 'model':
                        model = attr.get('value')
                        break
        elif marketplace == 'tonnel':
            # Для Tonnel модель может быть в разных полях
            model = item.get('model') or item.get('modelName') or item.get('model_name')
        elif marketplace == 'mrkt':
            # Для MRKT используется modelName (судя по логам)
            model = item.get('modelName') or item.get('model') or item.get('model_name')
        
        if not model:
            model = 'N/A'
        
        logger.debug(f"[monitor] {marketplace}: Extracted name='{name}', model='{model}' from item keys: {list(item.keys())[:10]}")
        
        # Удаляем пометки редкости в скобках, чтобы совпадало с поиском как в /get
        model_clean = re.sub(r"\s*\([^)]*\)", "", model).strip()
        name_clean_for_search = re.sub(r"\s*\([^)]*\)", "", name).strip()
        
        # Извлекаем цену - для разных маркетплейсов поля могут отличаться
        price = None
        if marketplace == 'portals':
            price = item.get('price')
        elif marketplace == 'tonnel':
            price = item.get('price') or item.get('raw_price')
        elif marketplace == 'mrkt':
            # Для MRKT используется salePrice (судя по логам)
            price = item.get('salePrice') or item.get('price') or item.get('salePriceWithoutFee')
        
        # Преобразуем цену в float если нужно
        if price is not None:
            if isinstance(price, str):
                try:
                    price = float(price)
                except ValueError:
                    price = 0.0
            elif not isinstance(price, (int, float)):
                price = 0.0
        else:
            price = 0.0
        
        # Конвертируем из nanoTON если нужно
        price_ton = price
        if price_ton and price_ton > 1000:
            price_ton = price_ton / 1e9
        
        logger.debug(f"[monitor] {marketplace}: Extracted price={price}, price_ton={price_ton} from item keys: {list(item.keys())[:15]}")
        
        gift_number = item.get('external_collection_number') or item.get('number') or item.get('giftNumber') or 'N/A'
        
        # Фильтруем пользователей по выбранным подаркам и фильтрам
        filtered_users = []
        for user_id in users:
            if await should_process_gift_for_user(user_id, name, model, price_ton):
                filtered_users.append(user_id)
        
        if not filtered_users:
            # Подарок не подходит ни под один критерий пользователей
            logger.debug(f"[monitor] {marketplace}: Gift {name} ({model}) doesn't match any user filters, skipping")
            return
        
        # Используем отфильтрованный список пользователей
        users = filtered_users
        logger.debug(f"[monitor] {marketplace}: After filtering, {len(users)} users will receive notification for {name} ({model})")
        
        # Для Portals редкость модели может быть в attributes
        model_rarity = item.get('model_rarity') or item.get('rarity')
        if not model_rarity and 'attributes' in item and isinstance(item['attributes'], list):
            for attr in item['attributes']:
                if isinstance(attr, dict) and attr.get('type') == 'model':
                    rarity_per_mille = attr.get('rarity_per_mille')
                    if rarity_per_mille is not None:
                        model_rarity = f"{rarity_per_mille}%"
                    break
        
        if not model_rarity:
            model_rarity = 'N/A'
        
        
        # Извлекаем ID найденного подарка для создания ссылок
        found_gift_id = None
        found_mrkt_hash = None
        
        if marketplace == 'portals':
            found_gift_id = (item.get('id') or item.get('gift_id') or item.get('nft_id') or 
                            item.get('giftId') or item.get('_id'))
            if found_gift_id:
                found_gift_id = str(found_gift_id)
        elif marketplace == 'tonnel':
            found_gift_id = item.get('gift_id') or item.get('id')
            if found_gift_id:
                found_gift_id = str(found_gift_id)
        elif marketplace == 'mrkt':
            found_mrkt_hash = (item.get('mrkt_hash') or item.get('hash') or item.get('hash_id') or 
                              item.get('token') or item.get('uuid') or item.get('id'))
            if found_mrkt_hash:
                found_mrkt_hash = str(found_mrkt_hash).replace('-', '')
        
        # Очищаем название для URL (убираем пробелы и спецсимволы)
        name_clean = re.sub(r'[^\w-]', '', name.replace(' ', ''))
        gift_link = f"https://t.me/nft/{name_clean}-{gift_number}"
        
        # Получаем флоры модели со всех маркетплейсов (как в /get)
        floors = {}  # Используем floors как в /get
        gift_links = {}  # Ссылки на подарки - для найденного маркетплейса используем найденный подарок
        
        # Для маркетплейса, где найден подарок, сразу создаем ссылку на найденный подарок
        if marketplace == 'portals' and found_gift_id:
            gift_links['Portals'] = f"https://t.me/portals/market?startapp=gift_{found_gift_id}"
        elif marketplace == 'tonnel' and found_gift_id:
            gift_links['Tonnel'] = f"https://t.me/tonnel_network_bot/gift?startapp={found_gift_id}"
        elif marketplace == 'mrkt' and found_mrkt_hash:
            gift_links['MRKT'] = f"https://t.me/mrkt/app?startapp={found_mrkt_hash}"
        
        # Оптимизация: получаем флоры со всех маркетплейсов параллельно
        async def get_portals_floor():
            try:
                portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                if not portals_auth:
                    if not auth_token:
                        auth_token = await init_auth()
                    portals_auth = auth_token
                
                if not portals_auth or not get_model_floor_price:
                    return None
                
                if inspect.iscoroutinefunction(get_model_floor_price):
                    return await get_model_floor_price(name_clean_for_search, model_clean, portals_auth)
                else:
                    return await asyncio.to_thread(get_model_floor_price, name_clean_for_search, model_clean, portals_auth)
            except Exception as e:
                logger.debug(f"Error getting Portals floor: {e}")
                return None
        
        async def get_tonnel_floor():
            try:
                if not TONNEL_AUTH or not get_tonnel_model_floor_price:
                    return None
                return await asyncio.to_thread(get_tonnel_model_floor_price, name_clean_for_search, model_clean, TONNEL_AUTH)
            except Exception as e:
                logger.debug(f"Error getting Tonnel floor: {e}")
                return None
        
        async def get_mrkt_floor():
            try:
                if not MRKT_AUTH or not get_mrkt_model_floor_price:
                    return None
                return await asyncio.to_thread(get_mrkt_model_floor_price, name_clean_for_search, model_clean, MRKT_AUTH)
            except Exception as e:
                logger.debug(f"Error getting MRKT floor: {e}")
                return None
        
        # Выполняем все запросы параллельно
        portals_floor, tonnel_floor, mrkt_floor = await asyncio.gather(
            get_portals_floor(),
            get_tonnel_floor(),
            get_mrkt_floor(),
            return_exceptions=True
        )
        
        # Обрабатываем результаты
        floors['Portals'] = portals_floor if not isinstance(portals_floor, Exception) and portals_floor else None
        floors['Tonnel'] = tonnel_floor if not isinstance(tonnel_floor, Exception) and tonnel_floor and tonnel_floor != 0 else None
        floors['MRKT'] = mrkt_floor if not isinstance(mrkt_floor, Exception) and mrkt_floor else None
        
        # Получаем ссылки на подарки параллельно (только если нужно)
        async def get_portals_link():
            if floors['Portals'] and 'Portals' not in gift_links:
                try:
                    portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                    if inspect.iscoroutinefunction(search):
                        portals_items = await search(gift_name=name_clean_for_search, model=model_clean, limit=1, sort="price_asc", authData=portals_auth)
                    else:
                        portals_items = await asyncio.to_thread(search, gift_name=name_clean_for_search, model=model_clean, limit=1, sort="price_asc", authData=portals_auth)
                    if isinstance(portals_items, list) and portals_items:
                        gift_item = portals_items[0]
                        gift_id = gift_item.get('id') if isinstance(gift_item, dict) else (gift_item.id if hasattr(gift_item, 'id') else None)
                        if gift_id:
                            gift_links['Portals'] = f"https://t.me/portals/market?startapp=gift_{gift_id}"
                except Exception:
                    pass
        
        async def get_tonnel_link():
            if floors['Tonnel'] and 'Tonnel' not in gift_links and search_tonnel:
                try:
                    tonnel_items = await asyncio.to_thread(search_tonnel, gift_name=name_clean_for_search, model=model_clean, limit=1, sort="price_asc", authData=TONNEL_AUTH)
                    if isinstance(tonnel_items, list) and tonnel_items:
                        gift_id = tonnel_items[0].get('id') if isinstance(tonnel_items[0], dict) else tonnel_items[0].get('gift_id')
                        if gift_id:
                            gift_links['Tonnel'] = f"https://t.me/tonnel_network_bot/gift?startapp={gift_id}"
                except Exception:
                    pass
        
        async def get_mrkt_link():
            if floors['MRKT'] and 'MRKT' not in gift_links and search_mrkt:
                try:
                    mrkt_items = await asyncio.to_thread(search_mrkt, gift_name=name_clean_for_search, model=model_clean, limit=1, sort="price_asc", auth_token=MRKT_AUTH)
                    if isinstance(mrkt_items, list) and mrkt_items:
                        mrkt_hash = (mrkt_items[0].get('mrkt_hash') or mrkt_items[0].get('hash') or mrkt_items[0].get('hash_id') or 
                                   mrkt_items[0].get('token') or mrkt_items[0].get('uuid') or mrkt_items[0].get('id'))
                        if mrkt_hash:
                            gift_links['MRKT'] = f"https://t.me/mrkt/app?startapp={str(mrkt_hash).replace('-', '')}"
                except Exception:
                    pass
        
        # Получаем ссылки параллельно
        await asyncio.gather(
            get_portals_link(),
            get_tonnel_link(),
            get_mrkt_link(),
            return_exceptions=True
        )
        
        # GetGems удален
        
        # Определяем маркетплейс где найден подарок
        marketplace_name = {'portals': 'Portals', 'tonnel': 'Tonnel', 'mrkt': 'MRKT'}.get(marketplace, marketplace)
        
        # price_ton уже вычислен выше
        
        # Получаем ссылку на маркетплейс
        marketplace_link = gift_links.get(marketplace_name, '#')
        if marketplace == 'portals' and found_gift_id:
            marketplace_link = f"https://t.me/portals/market?startapp=gift_{found_gift_id}"
        elif marketplace == 'tonnel' and found_gift_id:
            marketplace_link = f"https://t.me/tonnel_network_bot/gift?startapp={found_gift_id}"
        elif marketplace == 'mrkt' and found_mrkt_hash:
            marketplace_link = f"https://t.me/mrkt/app?startapp={found_mrkt_hash}"
        
        
        # Получаем фон из атрибутов
        backdrop = None
        if 'attributes' in item and isinstance(item['attributes'], list):
            for attr in item['attributes']:
                if isinstance(attr, dict):
                    if attr.get('type') == 'backdrop' or attr.get('trait_type') == 'backdrop':
                        backdrop = attr.get('value')
                        break
        
        # Получаем флор гифта (коллекции) - делаем это параллельно с получением model floors
        gift_floor = None
        async def get_gift_floor_task():
            try:
                if marketplace == 'portals' and get_gift_floor_price:
                    portals_auth = PORTALS_AUTH if PORTALS_AUTH else auth_token
                    if portals_auth:
                        return await asyncio.to_thread(get_gift_floor_price, name_clean_for_search, portals_auth)
                elif marketplace == 'tonnel' and get_tonnel_gift_floor_price:
                    return await asyncio.to_thread(get_tonnel_gift_floor_price, name_clean_for_search, TONNEL_AUTH)
                elif marketplace == 'mrkt' and get_mrkt_gift_floor_price:
                    return await asyncio.to_thread(get_mrkt_gift_floor_price, name_clean_for_search, MRKT_AUTH)
            except Exception as e:
                logger.debug(f"Error getting gift floor price: {e}")
            return None
        
        # Запускаем получение gift_floor параллельно с другими операциями
        gift_floor_task = asyncio.create_task(get_gift_floor_task())
        
        # История продаж берем из Tonnel для всех маркетплейсов (только модели, не подарка)
        # Делаем это параллельно с получением gift_floor
        async def get_model_sales_task():
            try:
                if get_tonnel_model_sales_history and TONNEL_AUTH and model_clean and model_clean != 'N/A':
                    return await asyncio.to_thread(get_tonnel_model_sales_history, name_clean_for_search, model_clean, TONNEL_AUTH, 5)
            except Exception as e:
                logger.debug(f"Error getting model sales: {e}")
            return []
        
        model_sales_task = asyncio.create_task(get_model_sales_task())
        
        # Ждем завершения всех параллельных задач
        model_sales = await model_sales_task
        gift_floor = await gift_floor_task
        
        if gift_floor:
            logger.info(f"[monitor] Got gift floor for {name_clean_for_search}: {gift_floor} TON")
        
        # Определяем флор модели для текущего маркетплейса
        mp_names = {'portals': 'Portals', 'tonnel': 'Tonnel', 'mrkt': 'MRKT'}
        current_mp_name = mp_names.get(marketplace, marketplace)
        model_floor_value = floors.get(current_mp_name)
        
        # Определяем правильный gift_id для передачи в format_gift_message
        gift_id_for_message = None
        if marketplace == 'portals' and found_gift_id:
            gift_id_for_message = found_gift_id
        elif marketplace == 'tonnel' and found_gift_id:
            gift_id_for_message = found_gift_id
        elif marketplace == 'mrkt' and found_mrkt_hash:
            gift_id_for_message = found_mrkt_hash
        
        # Используем унифицированный формат вывода
        caption, keyboard = format_gift_message(
            marketplace=marketplace,
            name=name,
            model=model,
            price=price_ton,
            floor_price=floor_price,
            model_floor=model_floor_value,
            gift_floor=gift_floor,
            model_rarity=model_rarity,
            gift_number=str(gift_number),
            model_sales=model_sales,
            gift_id=gift_id_for_message,
            has_inscription=False
        )
        
        # Кнопка только для маркетплейса, где найден подарок
        if keyboard:
            pass  # уже создана внутри format_gift_message
        
        # Отправляем уведомления всем пользователям
        logger.info(f"Sending notifications to {len(users)} users: {users}")
        for user_id in users:
            try:
                if photo_url:
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=photo_url,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                else:
                    await bot.send_message(
                        chat_id=user_id,
                        text=caption,
                        parse_mode="HTML",
                        reply_markup=keyboard,
                        disable_web_page_preview=False
                    )
                logger.info(f"Successfully sent notification to user {user_id}")
            except Exception as e:
                logger.error(f"Error sending monitoring notification to user {user_id}: {e}", exc_info=True)
    
    except Exception as e:
        logger.error(f"Error processing new gift monitoring: {e}", exc_info=True)


# Обработчики меню и админ-панели
@dp.callback_query(lambda c: c.data == "menu_functions")
async def callback_menu_functions(callback: types.CallbackQuery):
    """Обработка нажатия на кнопку 'Функции'"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Сравнение цен", callback_data="func_compare_prices"),
            InlineKeyboardButton(text="🔔 Мониторинг новых", callback_data="func_monitoring")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")
        ]
    ])
    
    await callback.message.edit_text(
        "🔍 Функции\n\n"
        "Выберите функцию:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "func_compare_prices")
async def callback_func_compare_prices(callback: types.CallbackQuery):
    """Обработка нажатия на кнопку 'Сравнение цен'"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Команда /get удалена
    await callback.answer("❌ Команда /get удалена. Используйте кнопки в меню.", show_alert=True)


@dp.callback_query(lambda c: c.data == "func_monitoring")
async def callback_func_monitoring(callback: types.CallbackQuery):
    """Обработка нажатия на кнопку 'Мониторинг новых'"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Проверяем текущий статус мониторинга
    enabled = False
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT enabled FROM new_gifts_monitoring WHERE user_id = %s
                    """, (callback.from_user.id,))
                    result = await cur.fetchone()
                    if result:
                        enabled = bool(result[0])
        except Exception as e:
            logger.error(f"Error checking monitoring status: {e}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Включить мониторинг" if not enabled else "❌ Выключить мониторинг",
                callback_data="monitoring_toggle"
            )
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="menu_functions")
        ]
    ])
    
    status_text = "включен" if enabled else "выключен"
    await callback.message.edit_text(
        f"🔔 Мониторинг новых подарков\n\n"
        f"Текущий статус: {status_text}\n\n"
        f"При включении бот будет проверять новые подарки каждую секунду и отправлять уведомления.",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "monitoring_toggle")
async def callback_monitoring_toggle(callback: types.CallbackQuery):
    """Переключение мониторинга новых подарков"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к этой функции", show_alert=True)
        return
    
    if not db_pool:
        await callback.answer("❌ База данных не подключена", show_alert=True)
        return
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Проверяем текущий статус
                await cur.execute("""
                    SELECT enabled FROM new_gifts_monitoring WHERE user_id = %s
                """, (callback.from_user.id,))
                result = await cur.fetchone()
                
                new_status = True
                if result and result[0]:
                    new_status = False
                
                # Обновляем или создаем запись
                await cur.execute("""
                    INSERT INTO new_gifts_monitoring (user_id, enabled, enabled_at, last_check_at)
                    VALUES (%s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        enabled = %s,
                        enabled_at = CASE WHEN %s = TRUE THEN NOW() ELSE enabled_at END,
                        last_check_at = NOW()
                """, (callback.from_user.id, new_status, new_status, new_status))
                await conn.commit()
        
        status_text = "включен" if new_status else "выключен"
        await callback.answer(f"Мониторинг {status_text}", show_alert=True)
        
        # Обновляем меню
        await callback_func_monitoring(callback)
    
    except Exception as e:
        logger.error(f"Error toggling monitoring: {e}")
        await callback.answer("❌ Ошибка при изменении статуса", show_alert=True)


@dp.callback_query(lambda c: c.data == "menu_back")
async def callback_menu_back(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    if not await is_allowed_user(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить подарок", callback_data="menu_add"),
            InlineKeyboardButton(text="📋 Список подарков", callback_data="menu_list")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")
        ],
        [
            InlineKeyboardButton(text="🔍 Функции", callback_data="menu_functions")
        ]
    ])
    
    if await is_admin(callback.from_user.id):
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="👑 Админ-панель", callback_data="menu_admin")
        ])
    
    await callback.message.edit_text(
        "🤖 Бот мониторинга подарков\n\n"
        "Выберите действие:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu_admin")
async def callback_menu_admin(callback: types.CallbackQuery):
    """Обработка нажатия на кнопку 'Админ-панель'"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к админ-панели", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="admin_add_user"),
            InlineKeyboardButton(text="➖ Удалить пользователя", callback_data="admin_remove_user")
        ],
        [
            InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list_users")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")
        ]
    ])
    
    await callback.message.edit_text(
        "👑 Админ-панель\n\n"
        "Выберите действие:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_add_user")
async def callback_admin_add_user(callback: types.CallbackQuery, state: FSMContext):
    """Добавление пользователя админом"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "Введите Telegram ID пользователя для добавления:\n\n"
        "Чтобы узнать ID пользователя, попросите его написать боту @userinfobot"
    )
    await state.set_state(AdminStates.waiting_user_id)
    await callback.answer()


@dp.message(AdminStates.waiting_user_id)
async def admin_add_user_id(message: types.Message, state: FSMContext):
    """Обработка ввода ID пользователя для добавления"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        await state.clear()
        return
    
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Пожалуйста, введите числовой ID пользователя")
        return
    
    user_id = int(message.text)
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Получаем информацию о пользователе из bot_users
                await cur.execute("""
                    SELECT username, first_name FROM bot_users WHERE user_id = %s
                """, (user_id,))
                user_info = await cur.fetchone()
                
                username = user_info[0] if user_info else None
                first_name = user_info[1] if user_info else None
                
                # Добавляем в allowed_users
                await cur.execute("""
                    INSERT INTO allowed_users (user_id, username, first_name, added_by)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        username = VALUES(username),
                        first_name = VALUES(first_name)
                """, (user_id, username, first_name, message.from_user.id))
                await conn.commit()
        
        await message.answer(f"✅ Пользователь {user_id} добавлен в список разрешенных")
    
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        await message.answer(f"❌ Ошибка при добавлении пользователя: {str(e)}")
    
    await state.clear()


@dp.callback_query(lambda c: c.data == "admin_remove_user")
async def callback_admin_remove_user(callback: types.CallbackQuery, state: FSMContext):
    """Удаление пользователя админом"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "Введите Telegram ID пользователя для удаления:"
    )
    await state.set_state(AdminStates.waiting_remove_user_id)
    await callback.answer()


@dp.message(AdminStates.waiting_remove_user_id)
async def admin_remove_user_id(message: types.Message, state: FSMContext):
    """Обработка ввода ID пользователя для удаления"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        await state.clear()
        return
    
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Пожалуйста, введите числовой ID пользователя")
        return
    
    user_id = int(message.text)
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    DELETE FROM allowed_users WHERE user_id = %s
                """, (user_id,))
                await conn.commit()
        
        await message.answer(f"✅ Пользователь {user_id} удален из списка разрешенных")
    
    except Exception as e:
        logger.error(f"Error removing user: {e}")
        await message.answer(f"❌ Ошибка при удалении пользователя: {str(e)}")
    
    await state.clear()


@dp.callback_query(lambda c: c.data == "admin_list_users")
async def callback_admin_list_users(callback: types.CallbackQuery):
    """Список разрешенных пользователей"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT user_id, username, first_name, added_at
                    FROM allowed_users
                    ORDER BY added_at DESC
                    LIMIT 50
                """)
                users = await cur.fetchall()
        
        if not users:
            text = "📋 Список разрешенных пользователей пуст"
        else:
            text = "📋 Список разрешенных пользователей:\n\n"
            for (user_id, username, first_name, added_at) in users:
                name = first_name or username or f"ID: {user_id}"
                text += f"• {name} (ID: {user_id})\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        await callback.answer("❌ Ошибка при получении списка", show_alert=True)
    
    await callback.answer()


async def main():
    """Главная функция"""
    await init_db()
    await init_auth()
    
    # Инициализируем существующие подарки, чтобы не отправлять старые
    await init_existing_gifts()
    
    # Запускаем отслеживание цен в фоне
    asyncio.create_task(price_tracker())
    
    # Запускаем отслеживание новых подарков в фоне
    asyncio.create_task(new_gifts_tracker())
    
    # Запускаем мониторинг новых подарков каждую секунду
    asyncio.create_task(new_gifts_monitoring_tracker())
    
    logger.info("Bot started")
    await dp.start_polling(bot)


async def shutdown():
    """Закрытие соединений при остановке"""
    global db_pool
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
        asyncio.run(shutdown())