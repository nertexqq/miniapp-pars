"""Обработчики текстовых сообщений"""

from aiogram import Dispatcher
from .admin import AdminStates, admin_add_user_id, admin_remove_user_id


def register_messages(dp: Dispatcher):
    """Регистрирует обработчики сообщений"""
    # FSM обработчики для админ-панели
    from .admin import admin_add_user_id, admin_remove_user_id, AdminStates
    from .add_gift import AddGiftStates, process_gifts_search
    
    dp.message.register(admin_add_user_id, AdminStates.waiting_user_id)
    dp.message.register(admin_remove_user_id, AdminStates.waiting_remove_user_id)
    dp.message.register(process_gifts_search, AddGiftStates.waiting_search)

