"""Обработчики меню"""

from aiogram import Dispatcher, types
from ...keyboards.builders import get_main_menu_keyboard, get_settings_keyboard
from ...di import container
from ...repositories.marketplace_repo import MarketplaceRepository
from ...repositories.user_repo import UserRepository


def register_menu_callbacks(dp: Dispatcher):
    """Регистрирует callbacks меню"""
    dp.callback_query.register(callback_menu_main, lambda c: c.data == "menu_main")
    dp.callback_query.register(callback_menu_settings, lambda c: c.data == "menu_settings")
    dp.callback_query.register(callback_toggle_parsing, lambda c: c.data == "toggle_parsing")


async def callback_menu_main(callback: types.CallbackQuery):
    """Главное меню"""
    keyboard = await get_main_menu_keyboard(callback.from_user.id)
    await callback.message.edit_text(
        "🤖 Бот мониторинга подарков\n\nВыберите действие:",
        reply_markup=keyboard
    )
    await callback.answer()


async def callback_menu_settings(callback: types.CallbackQuery):
    """Меню настроек"""
    pool = await container.init_db_pool()
    marketplace_repo = MarketplaceRepository(pool)
    
    enabled = await marketplace_repo.get_enabled(callback.from_user.id)
    enabled_list = ', '.join(sorted(enabled)) if enabled else "Нет"
    
    keyboard = await get_settings_keyboard(enabled)
    
    await callback.message.edit_text(
        f"⚙️ <b>Настройки маркетплейсов</b>\n\n"
        f"Включенные маркетплейсы: <b>{enabled_list}</b>\n\n"
        f"Нажмите на маркетплейс, чтобы включить/выключить:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


async def callback_toggle_parsing(callback: types.CallbackQuery):
    """Переключение парсинга"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    
    # Получаем текущее состояние
    current_state = await user_repo.is_parsing_enabled(callback.from_user.id)
    
    # Переключаем
    new_state = not current_state
    await user_repo.toggle_parsing(callback.from_user.id, new_state)
    
    # Обновляем клавиатуру (только кнопка парсинга меняется, текст тот же)
    keyboard = await get_main_menu_keyboard(callback.from_user.id)
    
    status_text = "включен" if new_state else "выключен"
    
    # Сначала обновляем кнопки (edit_message_reply_markup — текст не меняется)
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            try:
                await callback.message.edit_text(
                    "🤖 Бот мониторинга подарков\n\nВыберите действие:",
                    reply_markup=keyboard
                )
            except Exception:
                pass
    await callback.answer(f"✅ Парсинг {status_text}")

