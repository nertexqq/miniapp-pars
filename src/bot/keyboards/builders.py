"""Построители клавиатур"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from typing import Set
from ..di import container
from ..repositories.user_repo import UserRepository
from ..config import settings


async def get_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главное меню"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    is_admin = await user_repo.is_admin(user_id)
    
    # Проверяем состояние парсинга
    parsing_enabled = await user_repo.is_parsing_enabled(user_id)
    
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Добавить подарок", callback_data="menu_add"),
            InlineKeyboardButton(text="📋 Список подарков", callback_data="menu_list")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton(
                text="🟢 Парсинг включен" if parsing_enabled else "🔴 Парсинг выключен",
                callback_data="toggle_parsing"
            )
        ]
    ]
    
    # Кнопка Mini App (мониторинг подарков в реальном времени)
    miniapp_url = getattr(settings, "MINIAPP_URL", None)
    if miniapp_url and miniapp_url.strip():
        keyboard.append([
            InlineKeyboardButton(
                text="📱 Мониторинг подарков",
                web_app=WebAppInfo(url=miniapp_url.strip().rstrip("/"))
            )
        ])
    
    if is_admin:
        keyboard.append([
            InlineKeyboardButton(text="👑 Админ-панель", callback_data="menu_admin")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def get_settings_keyboard(enabled_marketplaces: Set[str]) -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    keyboard = [
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
    ]
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_gifts_list_keyboard(gifts: list, page: int = 0, per_page: int = 15) -> InlineKeyboardMarkup:
    """Клавиатура списка подарков"""
    keyboard = []
    
    # Кнопки подарков
    for gift in gifts:
        model_text = f" ({gift.get('model')})" if gift.get('model') else ""
        text = f"{gift['name']}{model_text}"
        if len(text) > 64:  # Ограничение Telegram
            text = text[:61] + "..."
        keyboard.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"gift_delete_{gift['name']}_{gift.get('model') or 'any'}"
            )
        ])
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"list_page_{page - 1}"))
    if len(gifts) == per_page:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"list_page_{page + 1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_gifts_selection_keyboard(
    gifts: list,
    search_query: str = "",
    letter_index: int = 0,
    alphabet_keys: list = None,
    page: int = 0,
    total_pages: int = 1
) -> InlineKeyboardMarkup:
    """Клавиатура выбора подарков"""
    keyboard = []
    
    # Кнопки подарков
    for gift_name in gifts:
        if len(gift_name) > 64:
            gift_name = gift_name[:61] + "..."
        keyboard.append([
            InlineKeyboardButton(
                text=gift_name,
                callback_data=f"gift_select_{gift_name}"
            )
        ])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"gifts_page_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"gifts_page_{page + 1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Навигация по буквам
    if alphabet_keys and not search_query:
        letter_buttons = []
        prev_idx = max(0, letter_index - 1)
        next_idx = min(len(alphabet_keys) - 1, letter_index + 1)
        
        if letter_index > 0:
            letter_buttons.append(InlineKeyboardButton(
                text=f"◀️ {alphabet_keys[prev_idx]}",
                callback_data=f"gifts_letter_{prev_idx}"
            ))
        if letter_index < len(alphabet_keys) - 1:
            letter_buttons.append(InlineKeyboardButton(
                text=f"{alphabet_keys[next_idx]} ▶️",
                callback_data=f"gifts_letter_{next_idx}"
            ))
        
        if letter_buttons:
            keyboard.append(letter_buttons)
    
    # Кнопки действий
    action_buttons = []
    if not search_query:
        action_buttons.append(InlineKeyboardButton(text="🔍 Поиск", callback_data="gifts_search"))
    action_buttons.append(InlineKeyboardButton(text="✅ Любые подарки", callback_data="gift_select_any"))
    
    if action_buttons:
        keyboard.append(action_buttons)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_models_selection_keyboard(models: list, page: int = 0, per_page: int = 15) -> InlineKeyboardMarkup:
    """Клавиатура выбора моделей"""
    keyboard = []
    
    # Пагинация
    from ..utils.pagination import paginate_items
    page_items, total_items, total_pages = paginate_items(models, page, per_page)
    
    # Кнопки моделей
    for model in page_items:
        if len(model) > 64:
            model = model[:61] + "..."
        keyboard.append([
            InlineKeyboardButton(
                text=model,
                callback_data=f"model_select_{model}"
            )
        ])
    
    # Кнопка "Любые модели"
    keyboard.append([
        InlineKeyboardButton(text="✅ Любые модели", callback_data="model_select_any")
    ])
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"models_page_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"models_page_{page + 1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="gifts_back")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
