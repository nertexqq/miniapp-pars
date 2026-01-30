"""Команда /stats"""

from aiogram import types
from aiogram.filters import Command
from ...di import container
from ...repositories.gift_repo import GiftRepository


async def cmd_stats(message: types.Message):
    """Обработчик команды /stats"""
    pool = await container.init_db_pool()
    gift_repo = GiftRepository(pool)
    
    all_gifts = await gift_repo.get_by_user(message.from_user.id, page=0, per_page=1000)
    
    total = len(all_gifts)
    unique = len(set((g['name'], g.get('model')) for g in all_gifts))
    
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"Всего подарков: {total}\n"
        f"Уникальных: {unique}",
        parse_mode="HTML"
    )


