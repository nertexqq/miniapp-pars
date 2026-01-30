"""Регистрация всех хэндлеров"""

from aiogram import Dispatcher


def register_all_handlers(dp: Dispatcher):
    """Регистрирует все хэндлеры"""
    from . import commands, callbacks, messages
    
    # Регистрируем команды
    commands.register_commands(dp)
    
    # Регистрируем callbacks
    callbacks.register_callbacks(dp)
    
    # Регистрируем messages
    messages.register_messages(dp)


