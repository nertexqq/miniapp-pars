"""Обработчики настроек"""

from aiogram import Dispatcher, types
from ...keyboards.builders import get_settings_keyboard
from ...di import container
from ...repositories.marketplace_repo import MarketplaceRepository


def register_settings_callbacks(dp: Dispatcher):
    """Регистрирует callbacks настроек"""
    dp.callback_query.register(
        callback_toggle_marketplace,
        lambda c: c.data and c.data.startswith("toggle_marketplace_")
    )


async def callback_toggle_marketplace(callback: types.CallbackQuery):
    """Переключение маркетплейса"""
    marketplace = callback.data.replace("toggle_marketplace_", "")
    
    if marketplace not in ['portals', 'tonnel', 'mrkt']:
        await callback.answer("❌ Неверный выбор маркетплейса", show_alert=True)
        return
    
    pool = await container.init_db_pool()
    marketplace_repo = MarketplaceRepository(pool)
    
    # Получаем текущее состояние
    enabled = await marketplace_repo.get_enabled(callback.from_user.id)
    new_state = marketplace not in enabled
    
    # Переключаем
    await marketplace_repo.toggle(callback.from_user.id, marketplace, new_state)
    
    # Обновляем клавиатуру
    enabled = await marketplace_repo.get_enabled(callback.from_user.id)
    keyboard = await get_settings_keyboard(enabled)
    enabled_list = ', '.join(sorted(enabled)) if enabled else "Нет"
    
    # Сначала обновляем сообщение и кнопки, затем answer — так кнопки обновляются сразу
    try:
        await callback.message.edit_text(
            f"⚙️ <b>Настройки маркетплейсов</b>\n\n"
            f"Включенные маркетплейсы: <b>{enabled_list}</b>\n\n"
            f"Нажмите на маркетплейс, чтобы включить/выключить:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            await callback.message.edit_reply_markup(reply_markup=keyboard)
    marketplace_names = {'portals': 'Portals', 'tonnel': 'Tonnel', 'mrkt': 'MRKT'}
    await callback.answer(f"✅ {marketplace_names[marketplace]} {'включен' if new_state else 'выключен'}")


