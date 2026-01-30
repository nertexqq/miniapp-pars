"""Команды бота"""

from aiogram import Dispatcher
from aiogram.filters import Command

from .start import cmd_start
from .settings import cmd_settings
from .list import cmd_list
from .stats import cmd_stats


def register_commands(dp: Dispatcher):
    """Регистрирует все команды"""
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_settings, Command("settings"))
    dp.message.register(cmd_list, Command("list"))
    dp.message.register(cmd_stats, Command("stats"))


