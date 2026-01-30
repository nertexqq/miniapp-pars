"""
Модуль для работы с базой данных MySQL
Устарел - используется прямое подключение через aiomysql в bot.py
Этот файл оставлен для обратной совместимости
"""

import warnings

warnings.warn(
    "Модуль database.py устарел. Используется прямое подключение aiomysql в bot.py",
    DeprecationWarning
)

