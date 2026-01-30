"""
Веб-сервер для GUI мониторинга подарков
Запускается локально на http://localhost:5000
"""

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

from flask import Flask, render_template, jsonify, request, Response, send_from_directory
import requests
from flask_socketio import SocketIO, emit
import warnings
warnings.filterwarnings("ignore", message=".*Eventlet is deprecated.*", category=DeprecationWarning)
import eventlet

# Добавляем корневую директорию в путь для импорта модулей бота
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Импорты из проекта
try:
    from dotenv import load_dotenv
    # Подхватываем .env из корня проекта и из папки gui (если запуск идёт из gui)
    load_dotenv(project_root / '.env', override=False)
    load_dotenv(Path(__file__).parent / '.env', override=False)
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
except ImportError:
    search_tonnel = None
    get_tonnel_model_sales_history = None
    get_tonnel_gift_sales_history = None
else:
    try:
        from tonnelmp_wrapper import (
            get_tonnel_model_sales_history,
            get_tonnel_gift_sales_history,
            get_tonnel_model_floor_price,
            get_tonnel_gift_floor_price,
        )
    except ImportError:
        get_tonnel_model_sales_history = None
        get_tonnel_gift_sales_history = None
        get_tonnel_model_floor_price = None
        get_tonnel_gift_floor_price = None

try:
    from mrktmp_wrapper import search_mrkt
except ImportError:
    search_mrkt = None

try:
    from getgems_wrapper import search_getgems, get_getgems_model_floor_price, get_getgems_gift_floor_price
except ImportError:
    search_getgems = None
    get_getgems_model_floor_price = None
    get_getgems_gift_floor_price = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.getenv('GUI_SECRET_KEY', 'portals-gifts-gui-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')


@app.before_request
def log_request():
    """Логируем входящие запросы — в консоли видно, доходят ли запросы от Mini App"""
    if request.path.startswith('/api/') or request.path == '/':
        logger.info("→ %s %s", request.method, request.path)


@app.after_request
def add_cors_headers(response):
    """CORS для Telegram Mini App и GitHub Pages"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, ngrok-skip-browser-warning'
    return response


@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        return Response(status=204, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        })

# Глобальное состояние
monitoring_enabled = False
seen_gift_ids: Set[str] = set()
# Недавние подарки для fallback-поллинга
recent_gifts: List[Dict] = []
MAX_RECENT_GIFTS = 200
# Подсказки для выбора коллекций/моделей
known_collections: Set[str] = set()
known_models_by_collection: Dict[str, Set[str]] = {}
known_backgrounds_by_collection: Dict[str, Set[str]] = {}
known_gifts: Dict[str, Dict[str, str]] = {}
collection_images: Dict[str, str] = {}
model_images: Dict[str, str] = {}
background_images: Dict[str, str] = {}
gift_images: Dict[str, str] = {}
catalog_last_saved = 0.0

data_dir = Path(__file__).parent / "data"
images_dir = data_dir / "images"
for sub in ("collections", "models", "backgrounds", "gifts"):
    (images_dir / sub).mkdir(parents=True, exist_ok=True)

pending_downloads = []
pending_download_keys = set()
catalog_build_status = {
    "running": False,
    "portals_pages": 0,
    "tonnel_pages": 0,
    "items_processed": 0,
    "last_error": None,
}
# baseline_done = False означает: следующий полный проход цикла только запоминает текущие лоты,
# но не шлёт их в GUI. После этого baseline_done переключается в True, и дальше шлём только новые.
baseline_done = False
filters = {
    'marketplaces': ['portals', 'tonnel', 'mrkt', 'getgems'],
    # Списки коллекций/моделей/фонов как на Portals
    'collections': [],    # Collection
    'models': [],         # Model
    'backgrounds': [],    # Background
    'min_price': None,
    'max_price': None,
    # Сортировки как на Portals: latest, price_asc, price_desc,
    # gift_id_asc, gift_id_desc, model_rarity_asc, model_rarity_desc
    'sort': 'latest'
}

# Настройки из .env
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
PORTALS_AUTH = os.getenv('PORTALS_AUTH')
TONNEL_AUTH = os.getenv('TONNEL_AUTH')
MRKT_AUTH = os.getenv('MRKT_AUTH', '09661eb0-c776-4391-a01e-990306cceca2')
TONNEL_FEE_RATE = float(os.getenv('TONNEL_FEE_RATE', '0.06'))
GETGEMS_API_KEY = os.getenv('GETGEMS_API_KEY')

# Кэш для флоров (чтобы не дергать API на каждый лот)
FLOOR_CACHE_TTL = int(os.getenv('FLOOR_CACHE_TTL', '300'))
floor_cache = {
    'gift': {},
    'model': {},
}


def get_item_value(item, *keys, default=None):
    """Получает значение из объекта или словаря по ключам"""
    for key in keys:
        try:
            if isinstance(item, dict):
                value = item.get(key)
            else:
                # Для объектов используем getattr
                # Пробуем разные варианты имени атрибута
                value = None
                for attr_name in [key, key.replace('_', ''), f'_{key}']:
                    if hasattr(item, attr_name):
                        value = getattr(item, attr_name, None)
                        if value is not None:
                            break
                
                # Если не нашли через getattr, пробуем через __dict__
                if value is None and hasattr(item, '__dict__'):
                    value = item.__dict__.get(key)
            
            if value is not None:
                return value
        except (AttributeError, KeyError, TypeError):
            continue
    
    return default


def update_known_from_items(items: List):
    for item in items:
        name = get_item_value(item, 'name', 'collectionName', 'gift_name', default=None)
        model = get_item_value(item, 'model', 'modelName', 'model_name', default=None)
        backdrop = get_item_value(item, 'backdrop', 'background', 'backdropName', default=None)
        photo_url = get_item_value(item, 'photo_url', 'image_url', 'image', default=None)
        gift_number = get_item_value(item, 'external_collection_number', 'number', 'giftNumber', 'gift_number', default=None)
        if name and str(name).strip():
            collection_name = str(name).strip()
            known_collections.add(collection_name)
            if photo_url:
                _queue_download("collections", collection_name, str(photo_url))
            if model and str(model).strip() and str(model).strip() != 'N/A':
                model_name = str(model).strip()
                known_models_by_collection.setdefault(collection_name, set()).add(model_name)
                if photo_url:
                    _queue_download("models", f"{collection_name}::{model_name}", str(photo_url))
            if backdrop and str(backdrop).strip():
                backdrop_name = str(backdrop).strip()
                known_backgrounds_by_collection.setdefault(collection_name, set()).add(backdrop_name)
                if photo_url:
                    _queue_download("backgrounds", f"{collection_name}::{backdrop_name}", str(photo_url))
            if gift_number:
                gift_key = f"{collection_name}::{gift_number}"
                if gift_key not in known_gifts:
                    known_gifts[gift_key] = {
                        "key": gift_key,
                        "collection": collection_name,
                        "model": str(model).strip() if model else None,
                        "backdrop": str(backdrop).strip() if backdrop else None,
                        "number": str(gift_number),
                    }
                if photo_url:
                    _queue_download("gifts", gift_key, str(photo_url))
    _save_catalog()


def normalize_gift_id(item, marketplace: str) -> str:
    """Нормализует ID подарка для уникальности"""
    if marketplace == 'portals':
        gift_id = get_item_value(item, 'id', 'gift_id', 'nft_id', 'giftId')
        return f"portals_{gift_id}" if gift_id else None
    elif marketplace == 'tonnel':
        gift_id = get_item_value(item, 'gift_id', 'id')
        return f"tonnel_{gift_id}" if gift_id else None
    elif marketplace == 'mrkt':
        gift_id = get_item_value(item, 'mrkt_hash', 'id', 'giftId')
        return f"mrkt_{gift_id}" if gift_id else None
    elif marketplace == 'getgems':
        gift_id = get_item_value(item, 'gift_id', 'address', 'id', 'token_id')
        return f"getgems_{gift_id}" if gift_id else None
    return None


def _build_marketplace_link(marketplace: str, marketplace_id: Optional[str], marketplace_hash: Optional[str]) -> str:
    if marketplace == 'portals' and marketplace_id:
        return f"https://t.me/portals/market?startapp=gift_{marketplace_id}"
    if marketplace == 'tonnel' and marketplace_id:
        return f"https://t.me/tonnel_network_bot/gift?startapp={marketplace_id}"
    if marketplace == 'mrkt':
        hash_value = marketplace_hash or marketplace_id
        if hash_value:
            return f"https://t.me/mrkt/app?startapp={str(hash_value).replace('-', '')}"
    if marketplace == 'getgems' and marketplace_id:
        return f"https://getgems.io/nft/{marketplace_id}"
    return "#"


def _normalize_price(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price > 1000:
        price = price / 1e9
    return round(price, 2)


def _apply_tonnel_fee(value):
    if value is None:
        return None
    if TONNEL_FEE_RATE <= 0:
        return value
    try:
        return round(float(value) * (1 + TONNEL_FEE_RATE), 2)
    except (TypeError, ValueError):
        return value


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "item"


def _file_name_for(value: str, url: str) -> str:
    slug = _slugify(value)
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    ext = Path(urlparse(url).path).suffix or ".jpg"
    if len(ext) > 5:
        ext = ".jpg"
    return f"{slug}-{digest}{ext}"


def _queue_download(kind: str, key: str, url: str):
    if not url:
        return
    # Убрано сохранение фоток подарков
    if kind == "gifts":
        return
    download_key = f"{kind}:{key}"
    if download_key in pending_download_keys:
        return
    pending_download_keys.add(download_key)
    pending_downloads.append((kind, key, url))


def _save_catalog():
    global catalog_last_saved
    if time.time() - catalog_last_saved < 5:
        return
    catalog_last_saved = time.time()
    payload = {
        "collections": sorted(known_collections),
        "models_by_collection": {k: sorted(list(v)) for k, v in known_models_by_collection.items()},
        "backgrounds_by_collection": {k: sorted(list(v)) for k, v in known_backgrounds_by_collection.items()},
        "gifts": list(known_gifts.values()),
        "collection_images": collection_images,
        "model_images": model_images,
        "background_images": background_images,
        "gift_images": gift_images,
        "updated_at": datetime.now().isoformat(),
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "catalog.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_catalog():
    catalog_path = data_dir / "catalog.json"
    if not catalog_path.exists():
        return
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        for name in payload.get("collections", []):
            known_collections.add(name)
        for collection, models in payload.get("models_by_collection", {}).items():
            known_models_by_collection.setdefault(collection, set()).update(models)
        for collection, bgs in payload.get("backgrounds_by_collection", {}).items():
            known_backgrounds_by_collection.setdefault(collection, set()).update(bgs)
        for gift in payload.get("gifts", []):
            gift_key = gift.get("key")
            if gift_key:
                known_gifts[gift_key] = gift
        collection_images.update(payload.get("collection_images", {}))
        model_images.update(payload.get("model_images", {}))
        background_images.update(payload.get("background_images", {}))
        gift_images.update(payload.get("gift_images", {}))
    except Exception as e:
        logger.warning(f"Failed to load catalog: {e}")


def _download_loop():
    while True:
        if not pending_downloads:
            eventlet.sleep(1)
            continue
        kind, key, url = pending_downloads.pop(0)
        try:
            file_name = _file_name_for(key, url)
            target_dir = images_dir / kind
            target_path = target_dir / file_name
            if not target_path.exists():
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
                target_path.write_bytes(resp.content)
            rel_path = str(target_path.relative_to(data_dir))
            if kind == "collections":
                collection_images[key] = rel_path
            elif kind == "models":
                model_images[key] = rel_path
            elif kind == "backgrounds":
                background_images[key] = rel_path
            elif kind == "gifts":
                # Убрано сохранение фоток подарков - не сохраняем
                pass
            if kind != "gifts":
                _save_catalog()
        except Exception as e:
            logger.debug(f"Image download failed for {url}: {e}")
        finally:
            pending_download_keys.discard(f"{kind}:{key}")
        eventlet.sleep(0.2)


def _portals_headers(auth_token: str) -> Dict[str, str]:
    auth_header = auth_token if auth_token and auth_token.startswith('tma ') else (f"tma {auth_token}" if auth_token else "")
    return {
        "Authorization": auth_header,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://portal-market.com",
        "Referer": "https://portal-market.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def _build_portals_catalog(max_pages: int = 200, limit: int = 30):
    if not PORTALS_AUTH:
        return
    base_url = "https://portal-market.com/api/nfts/search"
    for page in range(max_pages):
        offset = page * limit
        url = (
            f"{base_url}?offset={offset}&limit={limit}"
            "&sort_by=listed_at+desc&status=listed&exclude_bundled=true&premarket_status=all"
        )
        try:
            resp = requests.get(url, headers=_portals_headers(PORTALS_AUTH), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = []
            if isinstance(data, dict):
                items = data.get("results") or data.get("items") or []
            elif isinstance(data, list):
                items = data
            if not items:
                break
            update_known_from_items(items)
            catalog_build_status["portals_pages"] = page + 1
            catalog_build_status["items_processed"] += len(items)
        except Exception as e:
            catalog_build_status["last_error"] = f"portals: {e}"
            break
        eventlet.sleep(0.1)


def _build_tonnel_catalog(max_pages: int = 200, limit: int = 30):
    if not TONNEL_AUTH:
        return
    url = "https://gifts2.tonnel.network/api/pageGifts"
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://market.tonnel.network",
        "referer": "https://market.tonnel.network/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    sort_json = json.dumps({"message_post_time": -1, "gift_id": -1})
    filter_data = {
        "price": {"$exists": True},
        "refunded": {"$ne": True},
        "buyer": {"$exists": False},
        "export_at": {"$exists": True},
        "asset": "TON",
    }
    for page in range(1, max_pages + 1):
        try:
            json_data = {
                "page": page,
                "limit": limit,
                "sort": sort_json,
                "filter": json.dumps(filter_data, ensure_ascii=False),
                "price_range": None,
                "user_auth": TONNEL_AUTH or "",
            }
            resp = requests.post(url, headers=headers, json=json_data, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = []
            if isinstance(data, dict):
                items = data.get("items") or data.get("data") or data.get("results") or data.get("gifts") or []
            elif isinstance(data, list):
                items = data
            if not items:
                break
            update_known_from_items(items)
            catalog_build_status["tonnel_pages"] = page
            catalog_build_status["items_processed"] += len(items)
        except Exception as e:
            catalog_build_status["last_error"] = f"tonnel: {e}"
            break
        eventlet.sleep(0.1)


def _build_catalog():
    if catalog_build_status["running"]:
        return
    catalog_build_status["running"] = True
    catalog_build_status["last_error"] = None
    try:
        _build_portals_catalog()
        _build_tonnel_catalog()
    finally:
        catalog_build_status["running"] = False


_load_catalog()
eventlet.spawn_n(_download_loop)
if not (data_dir / "catalog.json").exists():
    eventlet.spawn_n(_build_catalog)


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


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
            if inspect.iscoroutinefunction(get_gift_floor_price):
                gift_floor = _run_async(get_gift_floor_price(name, PORTALS_AUTH))
            else:
                gift_floor = get_gift_floor_price(name, PORTALS_AUTH)
        if model_floor is None and get_model_floor_price and model and model != 'N/A':
            if inspect.iscoroutinefunction(get_model_floor_price):
                model_floor = _run_async(get_model_floor_price(name, model, PORTALS_AUTH))
            else:
                model_floor = get_model_floor_price(name, model, PORTALS_AUTH)
    except Exception as e:
        logger.warning(f"Error getting Portals floors for {name}/{model}: {e}")

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
            gift_floor = get_tonnel_gift_floor_price(name, TONNEL_AUTH)
        if model_floor is None and get_tonnel_model_floor_price and model and model != 'N/A':
            model_floor = get_tonnel_model_floor_price(name, model, TONNEL_AUTH)
    except Exception as e:
        logger.warning(f"Error getting Tonnel floors for {name}/{model}: {e}")

    if gift_floor is not None:
        _set_cached_floor('gift', gift_key, gift_floor)
    if model_key and model_floor is not None:
        _set_cached_floor('model', model_key, model_floor)

    return gift_floor, model_floor


def _get_getgems_floors(name: str, model: str):
    if not name or not search_getgems:
        return None, None
    gift_key = f"getgems:{name.lower()}"
    model_key = f"getgems:{name.lower()}:{model.lower()}" if model else None

    gift_floor = _get_cached_floor('gift', gift_key)
    model_floor = _get_cached_floor('model', model_key) if model_key else None

    if gift_floor is not None and (model_floor is not None or not model_key):
        return gift_floor, model_floor

    try:
        api_key = GETGEMS_API_KEY
        if gift_floor is None and get_getgems_gift_floor_price:
            gift_floor = get_getgems_gift_floor_price(name, api_key=api_key)
        if model_floor is None and get_getgems_model_floor_price and model and model != 'N/A':
            model_floor = get_getgems_model_floor_price(name, model, api_key=api_key)
    except Exception as e:
        logger.warning(f"Error getting GetGems floors for {name}/{model}: {e}")

    if gift_floor is not None:
        _set_cached_floor('gift', gift_key, gift_floor)
    if model_key and model_floor is not None:
        _set_cached_floor('model', model_key, model_floor)

    return gift_floor, model_floor


def matches_filters(item, marketplace: str) -> bool:
    """Проверяет, соответствует ли подарок фильтрам"""
    # Маркетплейс
    if marketplace not in filters['marketplaces']:
        return False
    
    # Коллекции (список)
    if filters.get('collections'):
        name = get_item_value(item, 'name', 'collectionName', 'gift_name', default='')
        name_str = str(name).lower()
        if not any(col.lower() in name_str for col in filters['collections']):
            return False
    
    # Модели (список)
    if filters.get('models'):
        model = get_item_value(item, 'model', 'modelName', 'model_name', default='')
        model_str = str(model).lower()
        if not any(m.lower() in model_str for m in filters['models']):
            return False
    
    # Фоны (Background)
    if filters.get('backgrounds'):
        backdrop = get_item_value(item, 'backdrop', 'background', 'backdropName', default='')
        backdrop_str = str(backdrop).lower()
        if not any(bg.lower() in backdrop_str for bg in filters['backgrounds']):
            return False
    
    # Цена
    price = get_item_value(item, 'price', 'raw_price', default=0)
    if isinstance(price, str):
        try:
            price = float(price)
        except:
            price = 0
    elif price is None:
        price = 0
    
    # Конвертация из nanoTON если нужно
    if price > 1000:
        price = price / 1e9
    
    if filters['min_price'] is not None and price < filters['min_price']:
        return False
    
    if filters['max_price'] is not None and price > filters['max_price']:
        return False
    
    return True


def format_gift_data(item, marketplace: str) -> Dict:
    """Форматирует данные подарка для отправки в GUI"""
    name = get_item_value(item, 'name', 'collectionName', 'gift_name', default='Unknown')
    model = get_item_value(item, 'model', 'modelName', 'model_name', default='N/A')
    
    price = _normalize_price(get_item_value(item, 'price', 'raw_price', default=0)) or 0
    if marketplace == 'tonnel':
        price = _apply_tonnel_fee(price)
    
    photo_url = get_item_value(item, 'photo_url', 'image_url', 'image', default='')
    
    gift_id = normalize_gift_id(item, marketplace)
    
    gift_number = get_item_value(item, 'external_collection_number', 'number', 'giftNumber', 'gift_number', default='N/A')

    # Обновляем списки подсказок
    if name and str(name).strip():
        collection_name = str(name).strip()
        known_collections.add(collection_name)
        if model and str(model).strip() and str(model).strip() != 'N/A':
            model_name = str(model).strip()
            known_models_by_collection.setdefault(collection_name, set()).add(model_name)

    marketplace_id = None
    marketplace_hash = None
    if marketplace == 'portals':
        marketplace_id = get_item_value(item, 'id', 'gift_id', 'nft_id')
    elif marketplace == 'tonnel':
        marketplace_id = get_item_value(item, 'gift_id', 'id')
    elif marketplace == 'mrkt':
        marketplace_hash = get_item_value(item, 'mrkt_hash', 'hash', 'hash_id')
        marketplace_id = get_item_value(item, 'id', default=None)
    elif marketplace == 'getgems':
        marketplace_id = get_item_value(item, 'gift_id', 'address', 'id', 'token_id')

    floor_price = _normalize_price(get_item_value(item, 'floor_price', 'floorPrice', 'floor', default=None))
    model_floor_price = _normalize_price(get_item_value(item, 'model_floor_price', 'modelFloorPrice', 'model_floor', default=None))

    if marketplace == 'portals' and (floor_price is None or model_floor_price is None):
        fetched_gift_floor, fetched_model_floor = _get_portals_floors(str(name), str(model))
        if floor_price is None:
            floor_price = _normalize_price(fetched_gift_floor)
        if model_floor_price is None:
            model_floor_price = _normalize_price(fetched_model_floor)
    if marketplace == 'tonnel' and (floor_price is None or model_floor_price is None):
        fetched_gift_floor, fetched_model_floor = _get_tonnel_floors(str(name), str(model))
        if floor_price is None:
            floor_price = _normalize_price(fetched_gift_floor)
        if model_floor_price is None:
            model_floor_price = _normalize_price(fetched_model_floor)
    if marketplace == 'getgems' and (floor_price is None or model_floor_price is None):
        fetched_gift_floor, fetched_model_floor = _get_getgems_floors(str(name), str(model))
        if floor_price is None:
            floor_price = _normalize_price(fetched_gift_floor)
        if model_floor_price is None:
            model_floor_price = _normalize_price(fetched_model_floor)
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
        'marketplace_hash': marketplace_hash,
        'timestamp': datetime.now().isoformat()
    }


def fetch_marketplace(marketplace: str) -> List[Dict]:
    """Получает подарки с маркетплейса"""
    items = []
    
    try:
        if marketplace == 'portals' and portals_search:
            portals_auth = PORTALS_AUTH
            if not portals_auth and portals_update_auth:
                # Пробуем получить токен
                try:
                    if inspect.iscoroutinefunction(portals_update_auth):
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        portals_auth = loop.run_until_complete(portals_update_auth(API_ID, API_HASH))
                        loop.close()
                    else:
                        portals_auth = portals_update_auth(API_ID, API_HASH)
                except Exception as e:
                    logger.error(f"Error getting Portals auth: {e}")
            
            if portals_auth:
                try:
                    # Для Portals достаточно 30 элементов за один запрос
                    limit = 30
                    sort = filters.get('sort', 'latest')
                    
                    # Подготавливаем фильтры для Portals API
                    collections = filters.get('collections') or []
                    models = filters.get('models') or []
                    
                    search_kwargs = {
                        'limit': limit,
                        'sort': sort,
                        'authData': portals_auth,
                    }
                    if collections:
                        # aportalsmp/portalsmp умеют принимать и строку, и список
                        search_kwargs['gift_name'] = collections
                    if models:
                        search_kwargs['model'] = models
                    
                    if inspect.iscoroutinefunction(portals_search):
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        result = loop.run_until_complete(portals_search(**search_kwargs))
                        loop.close()
                    else:
                        result = portals_search(**search_kwargs)
                    
                    if isinstance(result, list):
                        items = result
                        # Конвертируем объекты PortalsGift в словари если нужно
                        converted_items = []
                        for item in items:
                            if not isinstance(item, dict):
                                # Если это объект, конвертируем в словарь
                                try:
                                    item_dict = {}
                                    # Пробуем разные способы получения данных
                                    if hasattr(item, '__dict__'):
                                        item_dict.update(item.__dict__)
                                    
                                    # Пробуем получить через атрибуты
                                    attrs_to_try = ['id', 'gift_id', 'nft_id', 'name', 'collectionName', 'gift_name',
                                                   'model', 'modelName', 'model_name', 'price', 'raw_price',
                                                   'photo_url', 'image_url', 'image', 'external_collection_number',
                                                   'number', 'giftNumber']
                                    for attr in attrs_to_try:
                                        if attr not in item_dict and hasattr(item, attr):
                                            try:
                                                value = getattr(item, attr)
                                                if value is not None:
                                                    item_dict[attr] = value
                                            except:
                                                pass
                                    
                                    # Если это dataclass или pydantic модель, пробуем dict()
                                    if not item_dict:
                                        try:
                                            if hasattr(item, '__dict__') or hasattr(item, 'dict'):
                                                if hasattr(item, 'dict'):
                                                    item_dict = item.dict()
                                                elif hasattr(item, 'model_dump'):
                                                    item_dict = item.model_dump()
                                        except:
                                            pass
                                    
                                    if item_dict:
                                        converted_items.append(item_dict)
                                    else:
                                        logger.warning(f"Could not convert PortalsGift object to dict: {type(item)}")
                                except Exception as e:
                                    logger.warning(f"Error converting PortalsGift object: {e}")
                                    continue
                            else:
                                converted_items.append(item)
                        items = converted_items
                    elif isinstance(result, dict):
                        items = result.get('results') or result.get('items') or []
                    update_known_from_items(items)
                except Exception as e:
                    logger.error(f"Error fetching Portals: {e}")
        
        elif marketplace == 'tonnel' and search_tonnel and TONNEL_AUTH:
            try:
                limit = 30
                sort = filters.get('sort', 'latest')

                # Подготавливаем фильтры для Tonnel API по аналогии с Portals:
                # collections -> gift_name, models -> model
                collections = filters.get('collections') or []
                models = filters.get('models') or []

                # Для тоннеля API обычно ищем по одной паре gift_name/model.
                # Берём первый элемент из списка, если он есть.
                gift_name = collections[0] if collections else None
                model = models[0] if models else None

                result = search_tonnel(
                    gift_name=gift_name,
                    model=model,
                    limit=limit,
                    sort=sort,
                    authData=TONNEL_AUTH,
                )

                if isinstance(result, list):
                    items = result
                elif isinstance(result, dict):
                    items = result.get('results') or result.get('items') or result.get('gifts') or []
                update_known_from_items(items)
            except Exception as e:
                logger.error(f"Error fetching Tonnel: {e}")
        
        elif marketplace == 'mrkt' and search_mrkt and MRKT_AUTH:
            try:
                limit = 20
                sort = filters.get('sort', 'latest')
                
                result = search_mrkt(limit=limit, sort=sort, auth_token=MRKT_AUTH)
                
                if isinstance(result, list):
                    items = result
                elif isinstance(result, dict):
                    items = result.get('gifts') or result.get('results') or result.get('items') or []
                update_known_from_items(items)
            except Exception as e:
                logger.error(f"Error fetching MRKT: {e}")

        elif marketplace == 'getgems' and search_getgems:
            try:
                limit = 30
                sort = filters.get('sort', 'latest')
                collections = filters.get('collections') or []
                models = filters.get('models') or []
                gift_name = collections[0] if collections else None
                model = models[0] if models else None

                result = search_getgems(
                    gift_name=gift_name,
                    model=model,
                    limit=limit,
                    sort=sort,
                    api_key=GETGEMS_API_KEY,
                )
                if isinstance(result, list):
                    items = result
                else:
                    items = []
                update_known_from_items(items)
            except Exception as e:
                logger.error(f"Error fetching GetGems: {e}")
    
    except Exception as e:
        logger.error(f"Error in fetch_marketplace({marketplace}): {e}", exc_info=True)
    
    return items


def monitoring_loop():
    """Основной цикл мониторинга"""
    global seen_gift_ids, monitoring_enabled, baseline_done
    
    logger.info("Monitoring loop started")
    
    while monitoring_enabled:
        try:
            # Получаем подарки со всех включенных маркетплейсов
            all_items = []
            
            for marketplace in filters['marketplaces']:
                items = fetch_marketplace(marketplace)
                for item in items:
                    if matches_filters(item, marketplace):
                        all_items.append((item, marketplace))
            
            # Обрабатываем новые подарки
            for item, marketplace in all_items:
                gift_id = normalize_gift_id(item, marketplace)
                
                if gift_id and gift_id not in seen_gift_ids:
                    seen_gift_ids.add(gift_id)
                    
                    # Пока baseline ещё не построен, запоминаем gift_id, но ничего не шлём в GUI.
                    # Это защищает от ситуации, когда при первом запуске прилетают последние N лотов.
                    if not baseline_done:
                        continue
                    
                    # Форматируем и отправляем через WebSocket
                    gift_data = format_gift_data(item, marketplace)
                    # Кладем в буфер для REST fallback
                    recent_gifts.append(gift_data)
                    if len(recent_gifts) > MAX_RECENT_GIFTS:
                        recent_gifts[:] = recent_gifts[-MAX_RECENT_GIFTS:]
                    # Отправляем всем подключенным клиентам (без to= означает broadcast)
                    socketio.emit('new_gift', gift_data, namespace='/')
                    logger.info(f"New gift: {gift_data['name']} ({gift_data['model']}) - {gift_data['price']} TON")
            
            # После первого успешного полного прохода считаем baseline построенным,
            # и дальше начинаем слать только действительно новые подарки.
            if not baseline_done:
                baseline_done = True
            
            # Ограничиваем размер seen_gift_ids
            if len(seen_gift_ids) > 10000:
                seen_gift_ids = set(list(seen_gift_ids)[-5000:])
            
            # Ждем перед следующей проверкой
            eventlet.sleep(1)  # Проверка каждую секунду
        
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}", exc_info=True)
            eventlet.sleep(5)
    
    logger.info("Monitoring loop stopped")


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/data/<path:filename>')
def serve_data(filename):
    """Раздача каталога изображений (для Mini App и GUI)"""
    return send_from_directory(data_dir, filename)


@app.route('/api/status', methods=['GET'])
def get_status():
    """Получить статус мониторинга"""
    return jsonify({
        'enabled': monitoring_enabled,
        'filters': filters
    })


@app.route('/api/gifts', methods=['GET'])
def get_recent_gifts():
    """Получить последние найденные подарки (fallback для GUI)"""
    return jsonify(recent_gifts[-MAX_RECENT_GIFTS:])


@app.route('/api/suggestions', methods=['GET'])
def get_suggestions():
    """Подсказки для выбора коллекций/моделей с флорами Portals/Tonnel"""
    suggestion_type = request.args.get('type', 'collection')
    collections_param = request.args.get('collections', '')
    collections = [c.strip() for c in collections_param.split(',') if c.strip()]

    if suggestion_type == 'collection':
        items = []
        for name in sorted(known_collections):
            items.append({
                'name': name,
            })
        return jsonify(items[:200])

    if suggestion_type == 'model':
        if not collections:
            return jsonify([])
        models = set()
        for collection in collections:
            models.update(known_models_by_collection.get(collection, set()))

        items = []
        for model in sorted(models):
            items.append({
                'name': model,
            })
        return jsonify(items[:200])

    return jsonify([])


@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    """Возвращает сохранённые списки коллекций/моделей/фонов и изображения."""
    return jsonify({
        "collections": sorted(known_collections),
        "models_by_collection": {k: sorted(list(v)) for k, v in known_models_by_collection.items()},
        "backgrounds_by_collection": {k: sorted(list(v)) for k, v in known_backgrounds_by_collection.items()},
        "collection_images": collection_images,
        "model_images": model_images,
        "background_images": background_images,
        "gift_images": gift_images,
        "build_status": catalog_build_status,
    })


@app.route('/api/catalog/build', methods=['POST'])
def build_catalog():
    """Запускает сбор каталога всех коллекций/моделей/фонов"""
    if not catalog_build_status["running"]:
        eventlet.spawn_n(_build_catalog)
    return jsonify({"started": True, "status": catalog_build_status})


@app.route('/api/gift_details', methods=['POST'])
def get_gift_details():
    """Детали подарка и история продаж из Tonnel"""
    data = request.get_json() or {}
    marketplace = data.get('marketplace')
    name = data.get('name') or ''
    model = data.get('model') or ''
    marketplace_id = data.get('marketplace_id') or data.get('marketplaceId')
    marketplace_hash = data.get('marketplace_hash') or data.get('marketplaceHash')

    marketplace_link = _build_marketplace_link(marketplace, marketplace_id, marketplace_hash)

    model_sales = []
    if TONNEL_AUTH:
        try:
            if get_tonnel_model_sales_history and name and model and model != 'N/A':
                model_sales = get_tonnel_model_sales_history(name, model, TONNEL_AUTH, 5)
        except Exception as e:
            logger.warning(f"Error fetching sales history: {e}")

    return jsonify({
        'marketplace_link': marketplace_link,
        'model_sales': model_sales,
        'gift_sales': [],
    })


@app.route('/api/toggle', methods=['POST'])
def toggle_monitoring():
    """Включить/выключить мониторинг"""
    global monitoring_enabled, baseline_done, seen_gift_ids
    
    data = request.get_json()
    enabled = data.get('enabled', False)
    
    if enabled and not monitoring_enabled:
        # Запускаем мониторинг через eventlet background task
        monitoring_enabled = True
        seen_gift_ids.clear()
        baseline_done = False  # первый проход после включения только снимет baseline
        socketio.start_background_task(monitoring_loop)
        logger.info("Monitoring enabled")
    elif not enabled and monitoring_enabled:
        # Останавливаем мониторинг
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
    
    data = request.get_json()
    
    if 'marketplaces' in data:
        filters['marketplaces'] = data['marketplaces']
    # Списки коллекций / моделей / фонов
    if 'collections' in data:
        filters['collections'] = [c.strip() for c in (data['collections'] or []) if c and str(c).strip()]
    if 'models' in data:
        filters['models'] = [m.strip() for m in (data['models'] or []) if m and str(m).strip()]
    if 'backgrounds' in data:
        filters['backgrounds'] = [b.strip() for b in (data['backgrounds'] or []) if b and str(b).strip()]
    if 'min_price' in data:
        filters['min_price'] = float(data['min_price']) if data['min_price'] else None
    if 'max_price' in data:
        filters['max_price'] = float(data['max_price']) if data['max_price'] else None
    if 'sort' in data:
        filters['sort'] = data['sort']
    
    # При изменении фильтров baseline перестаёт быть актуальным:
    # очищаем кэш id и просим цикл сначала снять новое "текущее" состояние рынка,
    # не рассылая старые лоты в GUI.
    seen_gift_ids.clear()
    baseline_done = False
    
    return jsonify({'success': True, 'filters': filters})


@socketio.on('connect')
def handle_connect():
    """Обработка подключения WebSocket"""
    logger.info('Client connected')
    emit('status', {'enabled': monitoring_enabled})


@socketio.on('disconnect')
def handle_disconnect():
    """Обработка отключения WebSocket"""
    logger.info('Client disconnected')


if __name__ == '__main__':
    logger.info("Starting GUI server on http://localhost:5000")
    logger.info("Open http://localhost:5000 in your browser")
    socketio.run(app, host='127.0.0.1', port=5000, debug=False, allow_unsafe_werkzeug=True)
