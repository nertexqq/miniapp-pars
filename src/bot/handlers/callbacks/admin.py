"""Обработчики админ-панели"""

from aiogram import Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from ...di import container
from ...repositories.user_repo import UserRepository
from ...keyboards.builders import get_main_menu_keyboard


class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_remove_user_id = State()


def register_admin_callbacks(dp: Dispatcher):
    """Регистрирует callbacks админ-панели"""
    dp.callback_query.register(callback_menu_admin, lambda c: c.data == "menu_admin")
    dp.callback_query.register(callback_admin_add_user, lambda c: c.data == "admin_add_user")
    dp.callback_query.register(callback_admin_remove_user, lambda c: c.data == "admin_remove_user")
    dp.callback_query.register(callback_admin_list_users, lambda c: c.data == "admin_list_users")


async def callback_menu_admin(callback: types.CallbackQuery):
    """Меню админ-панели"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    
    is_admin = await user_repo.is_admin(callback.from_user.id)
    if not is_admin:
        await callback.answer("❌ У вас нет доступа к админ-панели", show_alert=True)
        return
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="admin_add_user")],
        [types.InlineKeyboardButton(text="➖ Удалить пользователя", callback_data="admin_remove_user")],
        [types.InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list_users")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])
    
    await callback.message.edit_text(
        "👑 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


async def callback_admin_add_user(callback: types.CallbackQuery, state: FSMContext):
    """Добавление пользователя"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    
    is_admin = await user_repo.is_admin(callback.from_user.id)
    if not is_admin:
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "Введите ID пользователя для добавления в список разрешенных:"
    )
    await state.set_state(AdminStates.waiting_user_id)
    await callback.answer()


async def callback_admin_remove_user(callback: types.CallbackQuery, state: FSMContext):
    """Удаление пользователя"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    
    is_admin = await user_repo.is_admin(callback.from_user.id)
    if not is_admin:
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "Введите ID пользователя для удаления из списка разрешенных:"
    )
    await state.set_state(AdminStates.waiting_remove_user_id)
    await callback.answer()


async def callback_admin_list_users(callback: types.CallbackQuery):
    """Список пользователей"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    
    is_admin = await user_repo.is_admin(callback.from_user.id)
    if not is_admin:
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    # Получаем всех пользователей
    all_users = await user_repo.get_all()
    admins = [u.user_id for u in all_users if await user_repo.is_admin(u.user_id)]
    
    # Получаем разрешенных пользователей
    allowed_users = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT user_id FROM allowed_users")
            results = await cur.fetchall()
            allowed_users = [r['user_id'] for r in results]
    
    text = "📋 <b>Список пользователей</b>\n\n"
    text += f"👑 Админы: {len(admins)}\n"
    text += f"✅ Разрешенные: {len(allowed_users)}\n"
    text += f"📊 Всего: {len(all_users)}\n\n"
    
    if allowed_users:
        text += "<b>Разрешенные пользователи:</b>\n"
        for user_id in allowed_users[:20]:  # Показываем первые 20
            text += f"• {user_id}\n"
        if len(allowed_users) > 20:
            text += f"... и еще {len(allowed_users) - 20}"
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text="🔙 Назад", callback_data="menu_admin")
    ]])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()



