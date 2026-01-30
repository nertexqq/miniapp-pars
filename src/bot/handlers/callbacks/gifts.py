"""Обработчики подарков"""

from aiogram import Dispatcher, types
from ...di import container
from ...repositories.gift_repo import GiftRepository
from ...keyboards.builders import get_gifts_list_keyboard


def register_gift_callbacks(dp: Dispatcher):
    """Регистрирует callbacks подарков"""
    dp.callback_query.register(callback_menu_list, lambda c: c.data == "menu_list")
    dp.callback_query.register(
        callback_list_page,
        lambda c: c.data and c.data.startswith("list_page_")
    )
    dp.callback_query.register(
        callback_gift_delete,
        lambda c: c.data and c.data.startswith("gift_delete_")
    )


async def callback_menu_list(callback: types.CallbackQuery):
    """Список подарков"""
    await show_gifts_list_page(callback, 0)


async def callback_list_page(callback: types.CallbackQuery):
    """Пагинация списка"""
    page = int(callback.data.split("_")[-1])
    await show_gifts_list_page(callback, page)


async def callback_gift_delete(callback: types.CallbackQuery):
    """Удаление подарка"""
    parts = callback.data.replace("gift_delete_", "").split("_", 1)
    gift_name = parts[0]
    model = parts[1] if len(parts) > 1 and parts[1] != 'any' else None
    
    pool = await container.init_db_pool()
    gift_repo = GiftRepository(pool)
    
    await gift_repo.delete(callback.from_user.id, gift_name, model)
    # Обновляем список, answer будет в show_gifts_list_page
    await show_gifts_list_page(callback, 0, answer_text="✅ Подарок удален")


async def show_gifts_list_page(callback: types.CallbackQuery, page: int = 0, answer_text: str = None):
    """Показать страницу списка подарков. answer_text — текст для popup при answer (None = без popup)."""
    pool = await container.init_db_pool()
    gift_repo = GiftRepository(pool)
    
    gifts = await gift_repo.get_unique_by_user(callback.from_user.id, page=page, per_page=15)
    
    if not gifts:
        await callback.message.edit_text(
            "📋 Список подарков пуст.",
            reply_markup=None
        )
        await callback.answer(answer_text if answer_text else None)
        return
    
    text = f"📋 <b>Ваши подарки</b>\n\nСтраница {page + 1}\n\n"
    for i, gift in enumerate(gifts, 1):
        model_text = f" ({gift.get('model')})" if gift.get('model') else ""
        text += f"{i}. {gift['name']}{model_text}\n"
    
    keyboard = get_gifts_list_keyboard(gifts, page=page)
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise
    await callback.answer(answer_text if answer_text else None)

