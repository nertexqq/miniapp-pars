"""
Веб-сервер для Telegram Mini App мониторинга подарков
Запускается на http://localhost:5001 (или через ngrok)
"""
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="eventlet")

import asyncio
import inspect
import json
import logging
import os
import sys
import time
import re
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Optional, Set
from datetime import datetime

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
import eventlet

# Добавляем корневую директорию в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# .env
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / '.env', override=False)
except ImportError:
    pass

# Импорты маркетплейсов
try:
    from aportalsmp import search as portals_search, update_auth as portals_update_auth
    from aportalsmp import get_model_floor_price, get_gift_floor_price
except ImportError:
    try:
        from portalsmp import search as portals_search, update_auth as portals_update_auth
        from portalsmp import get_model_floor_price, get_gift_floor_price
    except ImportError:
        portals_search = None
        portals_update_auth = None
        get_model_floor_price = None
        get_gift_floor_price = None

try:
    from tonnelmp_wrapper import search_tonnel
    from tonnelmp_wrapper import (
        get_tonnel_model_sales_history,
        get_tonnel_gift_sales_history,
        get_tonnel_model_floor_price,
        get_tonnel_gift_floor_price,
    )
except ImportError:
    search_tonnel = None
    get_tonnel_model_sales_history = None
    get_tonnel_gift_sales_history = None
    get_tonnel_model_floor_price = None
    get_tonnel_gift_floor_price = None

try:
    from mrktmp_wrapper import search_mrkt, get_mrkt_model_floor_price, get_mrkt_gift_floor_price
except ImportError:
    search_mrkt = None
    get_mrkt_model_floor_price = None
    get_mrkt_gift_floor_price = None

try:
    from getgems_wrapper import search_getgems, get_getgems_model_floor_price, get_getgems_gift_floor_price
except ImportError:
    search_getgems = None
    get_getgems_model_floor_price = None
    get_getgems_gift_floor_price = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("mrktmp_wrapper").setLevel(logging.ERROR)

app = Flask(__name__, template_folder='.', static_folder='.')
app.config['SECRET_KEY'] = os.getenv('GUI_SECRET_KEY', 'portals-gifts-miniapp-secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# CORS
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, ngrok-skip-browser-warning'
    return response

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        return '', 204

# Глобальное состояние
monitoring_enabled = False
seen_gift_ids: Set[str] = set()
recent_gifts: List[Dict] = []
MAX_RECENT_GIFTS = 200

known_collections: Set[str] = set()
known_models_by_collection: Dict[str, Set[str]] = {}

filters = {
    'marketplaces': [],
    'collections': [],
    'models': [],
    'backgrounds': [],
    'min_price': None,
    'max_price': None,
    'sort': 'latest'
}

# Настройки
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
PORTALS_AUTH = os.getenv('PORTALS_AUTH')
TONNEL_AUTH = os.getenv('TONNEL_AUTH')
MRKT_AUTH = os.getenv('MRKT_AUTH', '')
GETGEMS_API_KEY = os.getenv('GETGEMS_API_KEY')
TONNEL_FEE_RATE = float(os.getenv('TONNEL_FEE_RATE', '0.06'))

# Кэш флоров
FLOOR_CACHE_TTL = int(os.getenv('FLOOR_CACHE_TTL', '300'))
floor_cache = {'gift': {}, 'model': {}}

baseline_done = False

def get_item_value(item, *keys, default=None):
    """Получает значение из объекта"""
    for key in keys:
        try:
            if hasattr(item, key):
                return getattr(item, key)
            elif isinstance(item, dict) and key in item:
                return item[key]
        except (AttributeError, KeyError, TypeError):
            pass
    return default

def normalize_gift_id(item, marketplace: str) -> str:
    """Нормализует ID подарка"""
    if marketplace == 'portals':
        gift_id = get_item_value(item, 'id', 'gift_id', 'nft_id')
        return f"portals_{gift_id}" if gift_id else None
    elif marketplace == 'tonnel':
        gift_id = get_item_value(item, 'gift_id', 'id')
        return f"tonnel_{gift_id}" if gift_id else None
    elif marketplace == 'mrkt':
        gift_id = get_item_value(item, 'mrkt_hash', 'id')
        return f"mrkt_{gift_id}" if gift_id else None
    elif marketplace == 'getgems':
        gift_id = get_item_value(item, 'gift_id', 'address', 'id')
        return f"getgems_{gift_id}" if gift_id else None
    return None

def _normalize_price(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        price = float(value)
        if price > 1000:
            price = price / 1e9
        return round(price, 2)
    except (TypeError, ValueError):
        return None

def _apply_tonnel_fee(value):
    if value is None or TONNEL_FEE_RATE <= 0:
        return value
    try:
        return round(float(value) * (1 + TONNEL_FEE_RATE), 2)
    except (TypeError, ValueError):
        return value

def _get_cached_floor(cache_key: str, key: str):
    entry = floor_cache.get(cache_key, {}).get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > FLOOR_CACHE_TTL:
        floor_cache.get(cache_key, {}).pop(key, None)
        return None
    return value

def _set_cached_floor(cache_key: str, key: str, value):
    if cache_key not in floor_cache:
        floor_cache[cache_key] = {}
    floor_cache[cache_key][key] = (time.time(), value)

def _portals_headers(auth_token: str) -> Dict[str, str]:
    auth_header = auth_token if auth_token and auth_token.startswith('tma ') else (f"tma {auth_token}" if auth_token else "")
    return {
        "Authorization": auth_header,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://portal-market.com",
        "Referer": "https://portal-market.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

def _get_portals_floors(name: str, model: str):
    if not name or not PORTALS_AUTH:
        return None, None
    
    gift_key = f"portals:{name.lower()}"
    model_key = f"portals:{name.lower()}:{model.lower()}" if model else None

    gift_floor = _get_cached_floor('gift', gift_key)
    model_floor = _get_cached_floor('model', model_key) if model_key else None

    if gift_floor is not None and (model_floor is not None or not model_key):
        return gift_floor, model_floor

    try:
        if gift_floor is None and get_gift_floor_price:
            gift_floor = _normalize_price(get_gift_floor_price(PORTALS_AUTH, name))
        if model_floor is None and get_model_floor_price and model and model != 'N/A':
            model_floor = _normalize_price(get_model_floor_price(PORTALS_AUTH, name, model))
    except Exception as e:
        logger.warning(f"Error getting Portals floors: {e}")

    if gift_floor is not None:
        _set_cached_floor('gift', gift_key, gift_floor)
    if model_key and model_floor is not None:
        _set_cached_floor('model', model_key, model_floor)

    return gift_floor, model_floor

def _get_tonnel_floors(name: str, model: str):
    if not name or not TONNEL_AUTH:
        return None, None
    
    gift_key = f"tonnel:{name.lower()}"
    model_key = f"tonnel:{name.lower()}:{model.lower()}" if model else None

    gift_floor = _get_cached_floor('gift', gift_key)
    model_floor = _get_cached_floor('model', model_key) if model_key else None

    if gift_floor is not None and (model_floor is not None or not model_key):
        return gift_floor, model_floor

    try:
        if gift_floor is None and get_tonnel_gift_floor_price:
            gift_floor = _normalize_price(get_tonnel_gift_floor_price(name))
        if model_floor is None and get_tonnel_model_floor_price and model and model != 'N/A':
            model_floor = _normalize_price(get_tonnel_model_floor_price(name, model))
    except Exception as e:
        logger.warning(f"Error getting Tonnel floors: {e}")

    if gift_floor is not None:
        _set_cached_floor('gift', gift_key, gift_floor)
    if model_key and model_floor is not None:
        _set_cached_floor('model', model_key, model_floor)

    return gift_floor, model_floor

def matches_filters(item, marketplace: str) -> bool:
    """Проверяет, соответствует ли подарок фильтрам"""
    if marketplace not in filters['marketplaces']:
        return False
    
    if filters.get('collections'):
        name = get_item_value(item, 'name', 'collectionName', 'gift_name', default='')
        name_str = str(name).lower()
        if not any(col.lower() in name_str for col in filters['collections']):
            return False
    
    if filters.get('models'):
        model = get_item_value(item, 'model', 'modelName', 'model_name', default='')
        model_str = str(model).lower()
        if not any(m.lower() in model_str for m in filters['models']):
            return False
    
    price = get_item_value(item, 'price', 'raw_price', default=0)
    if isinstance(price, str):
        try:
            price = float(price)
        except:
            price = 0
    elif price is None:
        price = 0
    
    if price > 1000:
        price = price / 1e9
    
    if filters['min_price'] is not None and price < filters['min_price']:
        return False
    if filters['max_price'] is not None and price > filters['max_price']:
        return False
    
    return True

def format_gift_data(item, marketplace: str) -> Dict:
    """Форматирует данные подарка"""
    name = get_item_value(item, 'name', 'collectionName', 'gift_name', default='Unknown')
    model = get_item_value(item, 'model', 'modelName', 'model_name', default='N/A')
    price = _normalize_price(get_item_value(item, 'price', 'raw_price', default=0)) or 0
    
    if marketplace == 'tonnel':
        price = _apply_tonnel_fee(price)
    
    photo_url = get_item_value(item, 'photo_url', 'image_url', 'image', default='')
    gift_id = normalize_gift_id(item, marketplace)
    gift_number = get_item_value(item, 'external_collection_number', 'number', 'giftNumber', 'gift_number', default='N/A')

    if name and str(name).strip():
        collection_name = str(name).strip()
        known_collections.add(collection_name)
        if model and str(model).strip() and str(model).strip() != 'N/A':
            if collection_name not in known_models_by_collection:
                known_models_by_collection[collection_name] = set()
            known_models_by_collection[collection_name].add(str(model).strip())

    marketplace_id = None
    if marketplace == 'portals':
        marketplace_id = get_item_value(item, 'id', 'gift_id', 'nft_id')
    elif marketplace == 'tonnel':
        marketplace_id = get_item_value(item, 'gift_id', 'id')
    elif marketplace == 'mrkt':
        marketplace_id = get_item_value(item, 'id', default=None)
    elif marketplace == 'getgems':
        marketplace_id = get_item_value(item, 'gift_id', 'address', 'id')

    floor_price = _normalize_price(get_item_value(item, 'floor_price', 'floorPrice', default=None))
    model_floor_price = _normalize_price(get_item_value(item, 'model_floor_price', 'modelFloorPrice', default=None))

    if marketplace == 'portals' and (floor_price is None or model_floor_price is None):
        fetched_gift_floor, fetched_model_floor = _get_portals_floors(str(name), str(model))
        if floor_price is None:
            floor_price = fetched_gift_floor
        if model_floor_price is None:
            model_floor_price = fetched_model_floor
    
    if marketplace == 'tonnel' and (floor_price is None or model_floor_price is None):
        fetched_gift_floor, fetched_model_floor = _get_tonnel_floors(str(name), str(model))
        if floor_price is None:
            floor_price = fetched_gift_floor
        if model_floor_price is None:
            model_floor_price = fetched_model_floor
    
    if marketplace == 'tonnel':
        floor_price = _apply_tonnel_fee(floor_price)
        model_floor_price = _apply_tonnel_fee(model_floor_price)
    
    return {
        'id': gift_id,
        'marketplace': marketplace,
        'name': str(name),
        'model': str(model),
        'price': round(price, 2),
        'photo_url': str(photo_url) if photo_url else '',
        'gift_number': str(gift_number),
        'floor_price': floor_price,
        'model_floor_price': model_floor_price,
        'marketplace_id': marketplace_id,
        'timestamp': datetime.now().isoformat()
    }

def fetch_marketplace(marketplace: str) -> List[Dict]:
    """Получает подарки с маркетплейса"""
    items = []
    
    try:
        if marketplace == 'portals' and portals_search:
            try:
                result = portals_search(PORTALS_AUTH) if PORTALS_AUTH else None
                if result and isinstance(result, list):
                    items = result[:50]  # Ограничиваем для Mini App
            except Exception as e:
                logger.error(f"Portals search error: {e}")
        
        elif marketplace == 'tonnel' and search_tonnel and TONNEL_AUTH:
            try:
                result = search_tonnel(TONNEL_AUTH, limit=50)
                if result and isinstance(result, list):
                    items = result
            except Exception as e:
                logger.error(f"Tonnel search error: {e}")
        
        elif marketplace == 'mrkt' and search_mrkt and MRKT_AUTH:
            try:
                result = search_mrkt(MRKT_AUTH, limit=50)
                if result and isinstance(result, list):
                    items = result
            except Exception as e:
                logger.error(f"MRKT search error: {e}")
        
        elif marketplace == 'getgems' and search_getgems:
            try:
                result = search_getgems(GETGEMS_API_KEY, limit=50) if GETGEMS_API_KEY else None
                if result and isinstance(result, list):
                    items = result
            except Exception as e:
                logger.error(f"GetGems search error: {e}")
    
    except Exception as e:
        logger.error(f"Error in fetch_marketplace({marketplace}): {e}")
    
    return items

def monitoring_loop():
    """Основной цикл мониторинга"""
    global seen_gift_ids, monitoring_enabled, baseline_done, recent_gifts
    
    logger.info("Monitoring loop started")
    
    while monitoring_enabled:
        try:
            if not filters['marketplaces']:
                eventlet.sleep(2)
                continue
            
            for marketplace in filters['marketplaces']:
                try:
                    items = fetch_marketplace(marketplace)
                    
                    for item in items:
                        if not matches_filters(item, marketplace):
                            continue
                        
                        gift_id = normalize_gift_id(item, marketplace)
                        if not gift_id:
                            continue
                        
                        if gift_id in seen_gift_ids:
                            continue
                        
                        seen_gift_ids.add(gift_id)
                        
                        if baseline_done:
                            gift_data = format_gift_data(item, marketplace)
                            recent_gifts.insert(0, gift_data)
                            if len(recent_gifts) > MAX_RECENT_GIFTS:
                                recent_gifts.pop()
                            
                            socketio.emit('new_gift', gift_data, broadcast=True)
                    
                    if not baseline_done:
                        baseline_done = True
                        logger.info("Baseline set, now emitting new gifts")
                
                except Exception as e:
                    logger.error(f"Error processing marketplace {marketplace}: {e}")
                
                eventlet.sleep(1)
            
            eventlet.sleep(int(os.getenv('CHECK_INTERVAL', '60')))
        
        except Exception as e:
            logger.error(f"Monitoring loop error: {e}")
            eventlet.sleep(5)
    
    logger.info("Monitoring loop stopped")

# Маршруты

@app.route('/')
def index():
    """Главная страница Mini App"""
    return send_from_directory('.', 'index.html')

@app.route('/style.css')
def style():
    return send_from_directory('.', 'style.css')

@app.route('/app.js')
def app_js():
    return send_from_directory('.', 'app.js')

@app.route('/api/status', methods=['GET'])
def get_status():
    """Получить статус мониторинга"""
    return jsonify({
        'enabled': monitoring_enabled,
        'filters': filters
    })

@app.route('/api/gifts', methods=['GET'])
def get_recent_gifts():
    """Получить последние найденные подарки"""
    return jsonify(recent_gifts)

@app.route('/api/suggestions', methods=['GET'])
def get_suggestions():
    """Подсказки для выбора коллекций/моделей"""
    suggestion_type = request.args.get('type', 'collection')
    
    if suggestion_type == 'collection':
        return jsonify(sorted(list(known_collections)))
    
    if suggestion_type == 'model':
        collections_param = request.args.get('collections', '')
        collections = [c.strip() for c in collections_param.split(',') if c.strip()]
        models = set()
        for collection in collections:
            models.update(known_models_by_collection.get(collection, []))
        return jsonify(sorted(list(models)))
    
    return jsonify([])

@app.route('/api/toggle', methods=['POST'])
def toggle_monitoring():
    """Включить/выключить мониторинг"""
    global monitoring_enabled, baseline_done, seen_gift_ids
    
    data = request.get_json() or {}
    enabled = data.get('enabled', False)
    
    if enabled and not monitoring_enabled:
        monitoring_enabled = True
        baseline_done = False
        seen_gift_ids.clear()
        recent_gifts.clear()
        eventlet.spawn_n(monitoring_loop)
        logger.info("Monitoring enabled")
    elif not enabled and monitoring_enabled:
        monitoring_enabled = False
        logger.info("Monitoring disabled")
    
    return jsonify({'enabled': monitoring_enabled})

@app.route('/api/filters', methods=['GET'])
def get_filters():
    """Получить текущие фильтры"""
    return jsonify(filters)

@app.route('/api/filters', methods=['POST'])
def update_filters():
    """Обновить фильтры"""
    global filters, baseline_done, seen_gift_ids
    
    data = request.get_json() or {}
    
    if 'marketplaces' in data:
        filters['marketplaces'] = data['marketplaces']
    if 'collections' in data:
        filters['collections'] = data['collections']
    if 'models' in data:
        filters['models'] = data['models']
    if 'backgrounds' in data:
        filters['backgrounds'] = data['backgrounds']
    if 'min_price' in data:
        filters['min_price'] = data['min_price']
    if 'max_price' in data:
        filters['max_price'] = data['max_price']
    if 'sort' in data:
        filters['sort'] = data['sort']
    
    # При изменении фильтров обновляем baseline
    seen_gift_ids.clear()
    baseline_done = False
    
    return jsonify({'filters': filters})

@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")

if __name__ == '__main__':
    logger.info("Starting Mini App server on http://localhost:5001")
    socketio.run(app, host='0.0.0.0', port=5001, debug=False, allow_unsafe_werkzeug=True)
