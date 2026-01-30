#!/usr/bin/env python3
"""Запуск бота из корня проекта: python run_bot.py"""
import sys
from pathlib import Path

# Корень проекта в PYTHONPATH
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Запуск как модуль
import subprocess
result = subprocess.run(
    [sys.executable, "-m", "src.bot.main"],
    cwd=root,
)
sys.exit(result.returncode)
