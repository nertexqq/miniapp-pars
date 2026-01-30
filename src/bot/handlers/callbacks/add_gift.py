"""Обработчики добавления подарков"""

import logging
from aiogram import Dispatcher, types
from aiogram.fsm.context import FSMContext
from ...di import container
from ...keyboards.builders import get_gifts_selection_keyboard

logger = logging.getLogger(__name__)


def register_add_gift_callbacks(dp: Dispatcher):
    """Регистрирует callbacks для добавления подарков"""
    dp.callback_query.register(callback_menu_add, lambda c: c.data == "menu_add")
    dp.callback_query.register(
        callback_gifts_page,
        lambda c: c.data and c.data.startswith("gifts_page_")
    )
    dp.callback_query.register(
        callback_gifts_letter,
        lambda c: c.data and c.data.startswith("gifts_letter_")
    )
    dp.callback_query.register(
        callback_gifts_search,
        lambda c: c.data == "gifts_search"
    )
    dp.callback_query.register(
        callback_gift_select,
        lambda c: c.data and (c.data.startswith("gift_select_") or c.data == "gift_select_any")
    )
    dp.callback_query.register(
        callback_gifts_back,
        lambda c: c.data == "gifts_back"
    )
    dp.callback_query.register(
        callback_model_select,
        lambda c: c.data and (c.data.startswith("model_select_") or c.data == "model_select_any")
    )
    dp.callback_query.register(
        callback_models_page,
        lambda c: c.data and c.data.startswith("models_page_")
    )


async def callback_menu_add(callback: types.CallbackQuery, state: FSMContext):
    """Обработка нажатия на кнопку 'Добавить подарок'"""
    await callback.message.edit_text("⏳ Загружаю список подарков...")
    
    # Получаем сервисы через DI
    parser_service = await container.get_parser_service()
    
    # Получаем все подарки
    all_gifts = await parser_service.get_all_gift_names()
    
    if not all_gifts:
        await callback.message.edit_text("❌ Не удалось загрузить подарки. Попробуйте позже.")
        await callback.answer()
        return
    
    # Группируем по алфавиту
    from ...utils.pagination import group_by_alphabet
    gifts_list = sorted(list(all_gifts))
    grouped = group_by_alphabet(gifts_list)
    alphabet_keys = list(grouped.keys())
    
    if not alphabet_keys:
        await callback.message.edit_text("❌ Список подарков пуст.")
        await callback.answer()
        return
    
    # Сохраняем данные в состояние
    await state.update_data(
        all_gifts=grouped,
        alphabet_keys=alphabet_keys,
        current_letter_index=0,
        search_query=""
    )
    
    # Показываем первую страницу
    await show_gifts_page(callback, state, 0)
    await callback.answer()


async def show_gifts_page(callback: types.CallbackQuery, state: FSMContext, letter_index: int = None):
    """Показать страницу с подарками по алфавиту"""
    data = await state.get_data()
    grouped = data.get('all_gifts', {})
    alphabet_keys = data.get('alphabet_keys', [])
    search_query = data.get('search_query', '')
    
    if letter_index is None:
        letter_index = data.get('current_letter_index', 0)
    
    if not alphabet_keys:
        await callback.message.edit_text("❌ Список подарков пуст.")
        return
    
    # Применяем поиск если есть
    from ...utils.pagination import filter_items_by_search, paginate_items
    if search_query:
        filtered_gifts = []
        for letter, gifts in grouped.items():
            filtered = filter_items_by_search(gifts, search_query)
            filtered_gifts.extend(filtered)
        filtered_gifts = sorted(filtered_gifts)
    else:
        # Показываем подарки для текущей буквы
        if letter_index >= len(alphabet_keys):
            letter_index = 0
        current_letter = alphabet_keys[letter_index]
        filtered_gifts = grouped.get(current_letter, [])
    
    if not filtered_gifts:
        text = f"🔍 Поиск: {search_query}\n\n❌ Подарки не найдены." if search_query else "❌ Подарки не найдены."
        keyboard = get_gifts_selection_keyboard([], search_query=search_query, letter_index=letter_index, alphabet_keys=alphabet_keys)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # Разбиваем на страницы (по 15 подарков на страницу)
    page = data.get('current_page', 0)
    page_items, total_items, total_pages = paginate_items(filtered_gifts, page, 15)
    
    # Формируем текст
    if search_query:
        text = f"🔍 Поиск: <b>{search_query}</b>\n\n"
    else:
        current_letter = alphabet_keys[letter_index] if letter_index < len(alphabet_keys) else alphabet_keys[0]
        text = f"📦 Подарки (буква <b>{current_letter}</b>)\n\n"
    
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    # Создаем клавиатуру
    keyboard = get_gifts_selection_keyboard(
        page_items,
        search_query=search_query,
        letter_index=letter_index,
        alphabet_keys=alphabet_keys,
        page=page,
        total_pages=total_pages
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def callback_gifts_page(callback: types.CallbackQuery, state: FSMContext):
    """Обработка переключения страницы"""
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    await state.update_data(current_page=page)
    await show_gifts_page(callback, state)
    await callback.answer()


async def callback_gifts_letter(callback: types.CallbackQuery, state: FSMContext):
    """Обработка переключения буквы"""
    letter_index = int(callback.data.split("_")[-1])
    await state.update_data(current_letter_index=letter_index, current_page=0)
    await show_gifts_page(callback, state, letter_index)
    await callback.answer()


async def callback_gifts_search(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поиска"""
    from ...handlers.messages.add_gift import AddGiftStates
    
    await state.set_state(AddGiftStates.waiting_search)
    await callback.message.edit_text(
        "🔍 Введите название подарка для поиска:",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ Отмена", callback_data="gifts_back")]
        ])
    )
    await callback.answer()


async def callback_gift_select(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора подарка"""
    if callback.data == "gift_select_any":
        gift_name = "ANY"
        # Для "ANY" сразу добавляем без выбора модели
        await add_gift_to_db(callback, state, gift_name, "ANY")
        await callback.answer()
        return
    else:
        gift_name = callback.data.replace("gift_select_", "")
    
    # Сохраняем выбранный подарок
    await state.update_data(selected_gift=gift_name)
    
    # Получаем модели для подарка
    try:
        parser_service = await container.get_parser_service()
        models = await parser_service.get_models_for_gift(gift_name)
    except Exception as e:
        logger.error(f"Error getting models for gift {gift_name}: {e}", exc_info=True)
        models = []
    
    # Показываем выбор моделей
    if models:
        # Сохраняем модели в состояние
        await state.update_data(selected_gift=gift_name, available_models=sorted(list(models)))
        
        # Показываем модели
        from ...keyboards.builders import get_models_selection_keyboard
        keyboard = get_models_selection_keyboard(sorted(list(models)), page=0)
        
        text = f"📦 <b>{gift_name}</b>\n\nВыберите модель:"
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        # Нет моделей - добавляем подарок без модели
        await add_gift_to_db(callback, state, gift_name, None)
    await callback.answer()


async def callback_gifts_back(callback: types.CallbackQuery, state: FSMContext):
    """Обработка кнопки назад"""
    data = await state.get_data()
    if data.get('selected_gift'):
        # Возвращаемся к выбору подарка
        await state.update_data(selected_gift=None, available_models=None)
        await show_gifts_page(callback, state)
    else:
        # Возвращаемся в главное меню
        from ...keyboards.builders import get_main_menu_keyboard
        keyboard = await get_main_menu_keyboard(callback.from_user.id)
        await callback.message.edit_text(
            "🤖 Бот мониторинга подарков\n\nВыберите действие:",
            reply_markup=keyboard
        )
        await state.clear()
    await callback.answer()


async def add_gift_to_db(callback: types.CallbackQuery, state: FSMContext, gift_name: str, model: str = None):
    """Добавить подарок в базу данных"""
    from ...di import container
    from ...repositories.gift_repo import GiftRepository
    from ...repositories.marketplace_repo import MarketplaceRepository
    
    pool = await container.init_db_pool()
    gift_repo = GiftRepository(pool)
    marketplace_repo = MarketplaceRepository(pool)
    
    # Получаем включенные маркетплейсы
    enabled_marketplaces = await marketplace_repo.get_enabled(callback.from_user.id)
    
    if not enabled_marketplaces:
        await callback.answer("❌ Выберите хотя бы один маркетплейс в настройках", show_alert=True)
        return
    
    # Добавляем подарок для каждого включенного маркетплейса
    for marketplace in enabled_marketplaces:
        await gift_repo.add(
            user_id=callback.from_user.id,
            name=gift_name,
            model=model,
            marketplace=marketplace
        )
    
    model_text = f" ({model})" if model else ""
    await callback.answer(f"✅ Подарок {gift_name}{model_text} добавлен")
    
    # Возвращаемся в главное меню
    from ...keyboards.builders import get_main_menu_keyboard
    keyboard = await get_main_menu_keyboard(callback.from_user.id)
    await callback.message.edit_text(
        "🤖 Бот мониторинга подарков\n\nВыберите действие:",
        reply_markup=keyboard
    )
    await state.clear()


async def callback_model_select(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели"""
    data = await state.get_data()
    gift_name = data.get('selected_gift')
    
    if not gift_name:
        await callback.answer("❌ Ошибка: подарок не выбран", show_alert=True)
        return
    
    if callback.data == "model_select_any":
        model = "ANY"
    else:
        model = callback.data.replace("model_select_", "")
    
    # Добавляем подарок в базу
    await add_gift_to_db(callback, state, gift_name, model)


async def callback_models_page(callback: types.CallbackQuery, state: FSMContext):
    """Обработка переключения страницы моделей"""
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    
    models = data.get('available_models', [])
    from ...keyboards.builders import get_models_selection_keyboard
    keyboard = get_models_selection_keyboard(models, page=page)
    
    gift_name = data.get('selected_gift', 'Подарок')
    text = f"📦 <b>{gift_name}</b>\n\nВыберите модель:"
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

