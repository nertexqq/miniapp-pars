"""Команда /list"""

from aiogram import types
from aiogram.filters import Command
from ...di import container
from ...repositories.gift_repo import GiftRepository


async def cmd_list(message: types.Message):
    """Обработчик команды /list"""
    pool = await container.init_db_pool()
    gift_repo = GiftRepository(pool)
    
    gifts = await gift_repo.get_unique_by_user(message.from_user.id, page=0, per_page=15)
    
    if not gifts:
        await message.answer("📋 Список подарков пуст.")
        return
    
    text = "📋 <b>Ваши подарки:</b>\n\n"
    for i, gift in enumerate(gifts, 1):
        model_text = f" ({gift['model']})" if gift.get('model') else ""
        text += f"{i}. {gift['name']}{model_text}\n"
    
    await message.answer(text, parse_mode="HTML")


