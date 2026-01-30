"""Callbacks обработчики"""

from aiogram import Dispatcher


def register_callbacks(dp: Dispatcher):
    """Регистрирует все callbacks"""
    from .menu import register_menu_callbacks
    from .gifts import register_gift_callbacks
    from .settings import register_settings_callbacks
    from .admin import register_admin_callbacks
    from .add_gift import register_add_gift_callbacks
    
    register_menu_callbacks(dp)
    register_gift_callbacks(dp)
    register_settings_callbacks(dp)
    register_admin_callbacks(dp)
    register_add_gift_callbacks(dp)

