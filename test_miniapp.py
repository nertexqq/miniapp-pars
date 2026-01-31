#!/usr/bin/env python3
"""
Быстрая проверка, что miniapp сервер может быть импортирован
и API endpoints доступны
"""

import sys
from pathlib import Path

# Добавим miniapp в path
miniapp_dir = Path(__file__).parent / 'miniapp'
sys.path.insert(0, str(miniapp_dir))

try:
    # Импортируем сервер
    import server
    print("✅ miniapp/server.py импортируется успешно")
    
    # Проверяем, что Flask приложение создано
    assert hasattr(server, 'app'), "app не найден в server.py"
    print("✅ Flask приложение (app) найдено")
    
    # Проверяем, что socketio создан
    assert hasattr(server, 'socketio'), "socketio не найден в server.py"
    print("✅ Socket.IO найден")
    
    # Проверяем основные функции
    assert hasattr(server, 'fetch_marketplace'), "fetch_marketplace не найдена"
    print("✅ fetch_marketplace функция найдена")
    
    assert hasattr(server, 'format_gift_data'), "format_gift_data не найдена"
    print("✅ format_gift_data функция найдена")
    
    assert hasattr(server, 'monitoring_loop'), "monitoring_loop не найдена"
    print("✅ monitoring_loop функция найдена")
    
    # Проверяем API endpoints
    assert '/api/status' in [rule.rule for rule in server.app.url_map.iter_rules() if '/api/' in rule.rule]
    print("✅ /api/status endpoint зарегистрирован")
    
    assert '/api/gifts' in [rule.rule for rule in server.app.url_map.iter_rules() if '/api/' in rule.rule]
    print("✅ /api/gifts endpoint зарегистрирован")
    
    assert '/api/toggle' in [rule.rule for rule in server.app.url_map.iter_rules() if '/api/' in rule.rule]
    print("✅ /api/toggle endpoint зарегистрирован")
    
    assert '/api/filters' in [rule.rule for rule in server.app.url_map.iter_rules() if '/api/' in rule.rule]
    print("✅ /api/filters endpoint зарегистрирован")
    
    print("\n✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
    print("\nУстановка завершена успешно.")
    print("Запустите: python miniapp/server.py")
    print("Откройте: http://localhost:5001")
    
except Exception as e:
    print(f"❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
