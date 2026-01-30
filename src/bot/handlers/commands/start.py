"""Команда /start"""

from aiogram import types
from aiogram.filters import Command
from ...di import container
from ...repositories.user_repo import UserRepository
from ...models.entities import User
from ...keyboards.builders import get_main_menu_keyboard


async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    user_repo = UserRepository(await container.init_db_pool())
    
    # Сохраняем пользователя
    user = User(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        notifications_enabled=False
    )
    await user_repo.create_or_update(user)
    
    # Отправляем главное меню
    keyboard = await get_main_menu_keyboard(message.from_user.id)
    await message.answer(
        "🤖 Бот мониторинга подарков\n\nВыберите действие:",
        reply_markup=keyboard
    )


