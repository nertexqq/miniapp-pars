"""Обработчики сообщений для добавления подарков"""

from aiogram import Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


class AddGiftStates(StatesGroup):
    waiting_search = State()
    waiting_model = State()


def register_add_gift_messages(dp: Dispatcher):
    """Регистрирует message handlers для добавления подарков"""
    dp.message.register(process_gifts_search, AddGiftStates.waiting_search)


async def process_gifts_search(message: types.Message, state: FSMContext):
    """Обработка поискового запроса"""
    search_query = message.text.strip()
    
    if not search_query:
        await message.answer("❌ Введите название подарка для поиска:")
        return
    
    # Сохраняем поисковый запрос
    await state.update_data(search_query=search_query, current_page=0)
    
    # Создаем фейковый callback для показа результатов
    from ...handlers.callbacks.add_gift import show_gifts_page
    
    class FakeCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = message.from_user
    
    fake_callback = FakeCallback(message)
    await show_gifts_page(fake_callback, state)
    
    # Убираем состояние поиска
    await state.set_state(None)


