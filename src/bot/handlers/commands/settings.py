"""Команда /settings"""

from aiogram import types
from aiogram.filters import Command
from ...di import container
from ...repositories.marketplace_repo import MarketplaceRepository
from ...keyboards.builders import get_settings_keyboard


async def cmd_settings(message: types.Message):
    """Обработчик команды /settings"""
    pool = await container.init_db_pool()
    marketplace_repo = MarketplaceRepository(pool)
    
    enabled = await marketplace_repo.get_enabled(message.from_user.id)
    enabled_list = ', '.join(sorted(enabled)) if enabled else "Нет"
    
    keyboard = await get_settings_keyboard(enabled)
    
    await message.answer(
        f"⚙️ <b>Настройки маркетплейсов</b>\n\n"
        f"Включенные маркетплейсы: <b>{enabled_list}</b>\n\n"
        f"Нажмите на маркетплейс, чтобы включить/выключить:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


