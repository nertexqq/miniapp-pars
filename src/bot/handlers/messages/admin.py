"""Обработчики сообщений для админ-панели"""

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from ...di import container
from ...repositories.user_repo import UserRepository
from ...keyboards.builders import get_main_menu_keyboard


class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_remove_user_id = State()


async def admin_add_user_id(message: types.Message, state: FSMContext):
    """Обработка ввода ID пользователя для добавления"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    
    is_admin = await user_repo.is_admin(message.from_user.id)
    if not is_admin:
        await message.answer("❌ У вас нет доступа")
        await state.clear()
        return
    
    try:
        user_id = int(message.text.strip())
        
        # Добавляем в allowed_users
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO allowed_users (user_id)
                    VALUES (%s)
                    ON DUPLICATE KEY UPDATE user_id = user_id
                """, (user_id,))
                await conn.commit()
        
        await message.answer(f"✅ Пользователь {user_id} добавлен в список разрешенных")
        
        keyboard = await get_main_menu_keyboard(message.from_user.id)
        await message.answer("Выберите действие:", reply_markup=keyboard)
        
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число.")
        return
    
    await state.clear()


async def admin_remove_user_id(message: types.Message, state: FSMContext):
    """Обработка ввода ID пользователя для удаления"""
    pool = await container.init_db_pool()
    user_repo = UserRepository(pool)
    
    is_admin = await user_repo.is_admin(message.from_user.id)
    if not is_admin:
        await message.answer("❌ У вас нет доступа")
        await state.clear()
        return
    
    try:
        user_id = int(message.text.strip())
        pool = await container.init_db_pool()
        
        # Удаляем из allowed_users
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM allowed_users WHERE user_id = %s", (user_id,))
                await conn.commit()
        
        await message.answer(f"✅ Пользователь {user_id} удален из списка разрешенных")
        
        keyboard = await get_main_menu_keyboard(message.from_user.id)
        await message.answer("Выберите действие:", reply_markup=keyboard)
        
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число.")
        return
    
    await state.clear()

