"""
Обертка для работы с MRKT Marketplace API
Согласно документации: https://github.com/boostNT/MRKT-API
"""

import logging
from typing import List, Dict, Optional, Any
from urllib.parse import unquote

logger = logging.getLogger(__name__)

try:
    from curl_cffi import requests
except ImportError:
    import requests

# API URL согласно документации: https://github.com/boostNT/MRKT-API
MRKT_API_URL = 'https://api.tgmrkt.io/api/v1'


async def get_mrkt_auth_token(api_id: int, api_hash: str) -> Optional[str]:
    """
    Получение токена аутентификации для MRKT API через Pyrogram
    Согласно документации: https://github.com/boostNT/MRKT-API
    
    Args:
        api_id: API ID от Telegram
        api_hash: API Hash от Telegram
        
    Returns:
        Токен аутентификации или None в случае ошибки
    """
    try:
        from pyrogram import Client
        from pyrogram.raw.functions.messages import RequestAppWebView
        from pyrogram.raw.types import InputBotAppShortName, InputUser
        
        client = Client('mrkt_session', api_id=api_id, api_hash=api_hash)
        
        async with client:
            # Согласно документации, используем бота 'mrkt' с приложением 'app'
            bot_entity = await client.get_users('mrkt')
            peer = await client.resolve_peer('mrkt')
            
            bot = InputUser(user_id=bot_entity.id, access_hash=bot_entity.raw.access_hash)
            bot_app = InputBotAppShortName(bot_id=bot, short_name='app')
            
            web_view = await client.invoke(
                RequestAppWebView(
                    peer=peer,
                    app=bot_app,
                    platform="android",
                )
            )
            
            if 'tgWebAppData=' in web_view.url:
                init_data = unquote(web_view.url.split('tgWebAppData=', 1)[1].split('&tgWebAppVersion', 1)[0])
                
                # Отправляем POST запрос на https://api.tgmrkt.io/api/v1/auth
                auth_data = {"data": init_data}
                
                try:
                    if hasattr(requests, 'post'):
                        response = requests.post(
                            url='https://api.tgmrkt.io/api/v1/auth',
                            json=auth_data,
                            timeout=30
                        )
                    else:
                        import requests as std_requests
                        response = std_requests.post(
                            url='https://api.tgmrkt.io/api/v1/auth',
                            json=auth_data,
                            timeout=30
                        )
                    
                    if response.status_code == 200:
                        rj = response.json()
                        token = rj.get('token')
                        if token:
                            logger.info("MRKT auth token obtained successfully")
                            return token
                        else:
                            logger.error(f"MRKT auth response missing token: {rj}")
                    else:
                        logger.error(f"MRKT auth failed with status {response.status_code}: {response.text}")
                except Exception as e:
                    logger.error(f"Error getting MRKT auth token from API: {e}")
                    return None
            else:
                logger.error("No tgWebAppData found in web_view URL")
                return None
            
    except ImportError:
        logger.error("Pyrogram not installed. Cannot get MRKT auth token.")
        return None
    except Exception as e:
        logger.error(f"Error getting MRKT auth token: {e}", exc_info=True)
        return None


def search_mrkt(
    gift_name: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 30,
    sort: str = "price_asc",
    auth_token: Optional[str] = None
) -> List[Dict[str, Any]] | str:
    """
    Поиск подарков в MRKT Marketplace
    Согласно документации: https://github.com/boostNT/MRKT-API
    
    Args:
        gift_name: Название подарка
        model: Модель подарка
        limit: Максимальное количество результатов (максимум 20 согласно документации)
        sort: Тип сортировки (price_asc, price_desc, latest, etc.)
        auth_token: Токен аутентификации MRKT
        
    Returns:
        Список подарков или строка с ошибкой
    """
    if not auth_token:
        return "Error: auth_token required for MRKT"
    
    try:
        # Согласно документации, максимум 20 подарков за запрос
        if limit > 20:
            logger.warning(f"Limit {limit} exceeds maximum of 20, using 20 instead")
            limit = 20
        if limit < 1:
            limit = 1
        
        # Маппинг сортировки согласно документации
        # ordering: "Price" | "ModelRarity" | "BackgroundRarity" | "SymbolRarity" | None (по времени)
        ordering_map = {
            "price_asc": "Price",
            "price_desc": "Price",
            "latest": None,  # для последних — None означает сортировку по времени
            "model_rarity_asc": "ModelRarity",
            "model_rarity_desc": "ModelRarity",
            "backdrop_rarity_asc": "BackgroundRarity",
            "backdrop_rarity_desc": "BackgroundRarity",
            "symbol_rarity_asc": "SymbolRarity",
            "symbol_rarity_desc": "SymbolRarity",
        }
        
        ordering = ordering_map.get(sort, "Price")
        low_to_high = sort.endswith("_asc") or sort == "latest"
        
        # Формируем JSON body согласно документации
        json_data = {
            "collectionNames": [gift_name] if gift_name and gift_name.strip() else [],
            "modelNames": [model] if model and model.strip() else [],
            "backdropNames": [],
            "symbolNames": [],
            "lowToHigh": low_to_high,
            "maxPrice": None,
            "minPrice": None,
            "mintable": None,
            "number": None,
            "count": limit,
            "cursor": '',
            "query": None,
            "promotedFirst": False,
        }
        
        # Добавляем ordering только если оно не None
        if ordering is not None:
            json_data["ordering"] = ordering
        
        # Поле req - попробуем передать валидное значение
        # Согласно ошибке, поле требуется, но пустая строка не принимается
        # Попробуем передать строку с описанием запроса
        json_data["req"] = "search" if gift_name or model else "all"
        
        # Заголовки согласно документации
        # Токен используется напрямую без префикса "tma "
        headers = {
            "Authorization": auth_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        
        # Endpoint согласно документации: POST https://api.tgmrkt.io/api/v1/gifts/saling
        endpoint = f"{MRKT_API_URL}/gifts/saling"
        
        # Выполняем POST запрос с retry для 429 ошибок
        import time
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                if hasattr(requests, 'post'):
                    # Используем curl_cffi если доступен
                    if hasattr(requests, 'Session') and hasattr(requests.Session, 'impersonate'):
                        session = requests.Session(impersonate="chrome110")
                        response = session.post(endpoint, headers=headers, json=json_data, timeout=30)
                    else:
                        response = requests.post(endpoint, headers=headers, json=json_data, timeout=30)
                else:
                    import requests as std_requests
                    response = std_requests.post(endpoint, headers=headers, json=json_data, timeout=30)
            except Exception as e:
                logger.error(f"Error making request to MRKT API: {e}")
                if attempt < max_retries - 1:
                    # Используем очень короткую задержку, чтобы не блокировать event loop
                    time.sleep(0.1 * (attempt + 1))
                    continue
                return f"Error: Failed to perform request: {str(e)}"
            
            if response.status_code == 401:
                return "Auth error: invalid or expired token"
            
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    logger.warning(f"Rate limit (429) hit, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    time.sleep(wait_time)
                    continue
                else:
                    return f"Error: Rate limit exceeded (429) after {max_retries} attempts"
            
            if response.status_code != 200:
                logger.error(f"MRKT API returned status {response.status_code}: {response.text}")
                response.raise_for_status()
            
            break
        
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Error parsing JSON response: {e}")
            return f"Error: Invalid JSON response: {str(e)}"
        
        logger.info(f"MRKT API response type: {type(data)}, keys: {list(data.keys())[:10] if isinstance(data, dict) else 'N/A'}")
        
        # Согласно документации, ответ содержит поле "gifts"
        if isinstance(data, dict):
            items = data.get("gifts", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []
        
        logger.info(f"Extracted items: type={type(items)}, len={len(items) if isinstance(items, list) else 'N/A'}")
        
        if not isinstance(items, list):
            logger.error(f"Items is not a list: {type(items)}")
            return []
        
        # Логируем структуру первого элемента для отладки
        if items and isinstance(items[0], dict):
            first_item = items[0]
            logger.info(f"First MRKT API item keys: {list(first_item.keys())[:30]}")
            logger.info(f"First MRKT API item sample: {dict(list(first_item.items())[:20])}")
        
        # Преобразуем формат для совместимости
        result = []
        for item in items:
            if isinstance(item, dict):
                # Извлекаем цену - пробуем разные ключи
                # Цена может приходить в нанотонах (1 TON = 1,000,000,000 нанотонов)
                price = None
                price_fields = ['price', 'tonPrice', 'ton_price', 'priceTON', 'price_ton', 'amount', 'salePrice', 'sale_price', 'listPrice', 'list_price', 'raw_price']
                for field in price_fields:
                    if field in item:
                        price_val = item[field]
                        if price_val is not None:
                            try:
                                if isinstance(price_val, (int, float)):
                                    price_raw = float(price_val)
                                    # Если цена очень большая (> 1000), возможно это нанотоны, делим на 1e9
                                    # 1 TON = 1,000,000,000 нанотонов
                                    if price_raw > 1000:
                                        price_nano = price_raw / 1e9
                                        # Проверяем, имеет ли смысл (цена должна быть разумной, например 0.001-10000 TON)
                                        if 0.001 <= price_nano < 10000:
                                            price = price_nano
                                            logger.debug(f"Converted price from nanoTON: {price_raw} -> {price}")
                                        else:
                                            price = price_raw
                                    else:
                                        price = price_raw
                                elif isinstance(price_val, str):
                                    # Убираем TON, пробелы, запятые и пробуем преобразовать
                                    price_clean = price_val.replace('TON', '').replace('ton', '').replace(',', '').replace(' ', '').strip()
                                    if price_clean:
                                        price_raw = float(price_clean)
                                        # Проверяем нанотоны
                                        if price_raw > 1000:
                                            price_nano = price_raw / 1e9
                                            if 0.001 <= price_nano < 10000:
                                                price = price_nano
                                                logger.debug(f"Converted price from nanoTON: {price_raw} -> {price}")
                                            else:
                                                price = price_raw
                                        else:
                                            price = price_raw
                                if price and price > 0:
                                    logger.debug(f"Found price in field '{field}': {price}")
                                    break
                            except (ValueError, TypeError, AttributeError):
                                continue
                
                # Извлекаем флор - может быть в отдельном поле или нужно вычислять из коллекции
                # Флор также может приходить в нанотонах
                floor_price = None
                floor_fields = ['floorPrice', 'floor_price', 'collectionFloor', 'collection_floor', 'minPrice', 'min_price', 'floor']
                for field in floor_fields:
                    if field in item:
                        floor_val = item[field]
                        if floor_val is not None:
                            try:
                                if isinstance(floor_val, (int, float)):
                                    floor_raw = float(floor_val)
                                    # Если флор очень большой (> 1000), возможно это нанотоны
                                    if floor_raw > 1000:
                                        floor_nano = floor_raw / 1e9
                                        if 0.001 <= floor_nano < 10000:
                                            floor_price = floor_nano
                                            logger.debug(f"Converted floor_price from nanoTON: {floor_raw} -> {floor_price}")
                                        else:
                                            floor_price = floor_raw
                                    else:
                                        floor_price = floor_raw
                                elif isinstance(floor_val, str):
                                    floor_clean = floor_val.replace('TON', '').replace('ton', '').replace(',', '').replace(' ', '').strip()
                                    if floor_clean:
                                        floor_raw = float(floor_clean)
                                        # Проверяем нанотоны
                                        if floor_raw > 1000:
                                            floor_nano = floor_raw / 1e9
                                            if 0.001 <= floor_nano < 10000:
                                                floor_price = floor_nano
                                                logger.debug(f"Converted floor_price from nanoTON: {floor_raw} -> {floor_price}")
                                            else:
                                                floor_price = floor_raw
                                        else:
                                            floor_price = floor_raw
                                if floor_price and floor_price > 0:
                                    logger.debug(f"Found floor_price in field '{field}': {floor_price}")
                                    break
                            except (ValueError, TypeError, AttributeError):
                                continue
                
                # Если флор не найден, НЕ используем цену как fallback (это разные вещи)
                # floor_price остается None если не найден
                
                # Для MRKT ссылок нужен хеш (32 символа hex) - это поле id согласно документации
                item_id = item.get('id')
                
                # Проверяем, является ли id хешем (32 символа hex без дефисов)
                def is_hex_hash(value):
                    if not value:
                        return False
                    value_str = str(value).replace('-', '')
                    return len(value_str) == 32 and all(c in '0123456789abcdefABCDEF' for c in value_str)
                
                # Извлекаем хеш для ссылки
                mrkt_hash = None
                if item_id:
                    if is_hex_hash(item_id):
                        # Если id уже хеш, используем его
                        mrkt_hash = str(item_id).replace('-', '')
                        logger.debug(f"Using id as hash: {mrkt_hash}")
                    else:
                        # Ищем хеш в других полях (на случай если структура отличается)
                        hash_fields = ['hash', 'hashId', 'hash_id', 'token', 'uuid', 'guid', 'appId', 'app_id', 'startappId', 'startapp_id']
                        for field in hash_fields:
                            hash_val = item.get(field)
                            if hash_val and is_hex_hash(hash_val):
                                mrkt_hash = str(hash_val).replace('-', '')
                                logger.debug(f"Found hash in field '{field}': {mrkt_hash}")
                                break
                
                # Извлекаем название подарка
                name = (
                    item.get('collectionName') or 
                    item.get('collection_name') or 
                    item.get('name') or 
                    item.get('giftName') or 
                    item.get('gift_name') or
                    'Unknown'
                )
                
                # Извлекаем модель
                model_name = (
                    item.get('modelName') or 
                    item.get('model_name') or 
                    item.get('model') or
                    'N/A'
                )
                
                # Извлекаем номер подарка
                gift_number = (
                    item.get('number') or 
                    item.get('giftNumber') or 
                    item.get('gift_number') or
                    item.get('externalCollectionNumber') or
                    item.get('external_collection_number') or
                    'N/A'
                )
                
                # Извлекаем фото
                photo_url = (
                    item.get('photoUrl') or 
                    item.get('photo_url') or 
                    item.get('imageUrl') or 
                    item.get('image_url') or 
                    item.get('image') or
                    item.get('photo') or
                    None
                )
                
                # Извлекаем редкость модели
                model_rarity = (
                    item.get('modelRarity') or 
                    item.get('model_rarity') or 
                    item.get('rarity') or
                    item.get('modelRarityPercent') or
                    item.get('model_rarity_percent') or
                    None
                )
                
                converted = {
                    'id': item_id,
                    'mrkt_hash': mrkt_hash,  # Хеш для ссылки в мини-приложение (32 символа hex)
                    'name': name,
                    'model': model_name,
                    'price': price,
                    'floor_price': floor_price,  # Не используем price как fallback
                    'photo_url': photo_url,
                    'model_rarity': model_rarity,
                    'external_collection_number': str(gift_number),
                }
                result.append(converted)
                logger.debug(f"Converted MRKT item: name={name}, model={model_name}, price={price}, floor={floor_price}, hash={mrkt_hash}")
        
        return result
    except Exception as e:
        logger.error(f"Error in search_mrkt: {e}", exc_info=True)
        return f"Error: {str(e)}"


def get_mrkt_model_floor_price(gift_name: str, model: str, auth_token: str) -> Optional[float]:
    """
    Получение флор-цены для конкретной модели подарка в MRKT
    Использует search_mrkt() напрямую
    
    Args:
        gift_name: Название подарка
        model: Название модели
        auth_token: Токен аутентификации
        
    Returns:
        Флор-цена модели или None
    """
    try:
        logger.info(f"get_mrkt_model_floor_price called for '{gift_name}' / '{model}'")
        
        items = search_mrkt(
            gift_name=gift_name,
            model=model,
            limit=20,  # Максимум согласно документации
            sort="price_asc",
            auth_token=auth_token
        )
        
        if isinstance(items, str):
            logger.error(f"search_mrkt returned error: {items}")
            return None
        
        if not isinstance(items, list) or not items:
            logger.warning(f"No items found for '{gift_name}' / '{model}'")
            return None
        
        # Находим минимальную цену (флор)
        prices = []
        for item in items:
            if isinstance(item, dict):
                price = item.get('price')
                if price and isinstance(price, (int, float)) and price > 0:
                    prices.append(float(price))
        
        if prices:
            result = min(prices)
            logger.info(f"get_mrkt_model_floor_price result: {result} TON (from {len(prices)} prices)")
            return result
        else:
            logger.warning(f"No valid prices found in {len(items)} items")
            return None
    except Exception as e:
        logger.error(f"Error getting MRKT model floor price: {e}", exc_info=True)
        return None


def get_mrkt_gift_floor_price(gift_name: str, auth_token: str) -> Optional[float]:
    """
    Получение флор-цены для подарка (всех моделей) в MRKT
    
    Args:
        gift_name: Название подарка
        auth_token: Токен аутентификации
        
    Returns:
        Флор-цена подарка или None
    """
    try:
        items = search_mrkt(
            gift_name=gift_name,
            model=None,
            limit=20,
            sort="price_asc",
            auth_token=auth_token
        )
        
        if isinstance(items, str) or not isinstance(items, list) or not items:
            return None
        
        prices = []
        for item in items:
            if isinstance(item, dict):
                price = item.get('price')
                if price and isinstance(price, (int, float)) and price > 0:
                    prices.append(float(price))
        
        return min(prices) if prices else None
    except Exception as e:
        logger.error(f"Error getting MRKT gift floor price: {e}")
        return None


def get_mrkt_model_sales_history(gift_name: str, model: str, auth_token: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Получение истории продаж для модели подарка в MRKT
    Согласно документации, нужно использовать отдельный endpoint для продаж
    
    Args:
        gift_name: Название подарка
        model: Название модели
        auth_token: Токен аутентификации
        limit: Количество последних продаж
        
    Returns:
        Список продаж модели
    """
    try:
        headers = {
            "Authorization": auth_token,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Получаем подарки этой модели
        items = search_mrkt(
            gift_name=gift_name,
            model=model,
            limit=20,
            sort="latest",
            auth_token=auth_token
        )
        
        if isinstance(items, str) or not isinstance(items, list):
            return []
        
        # Собираем продажи для каждого подарка
        all_sales = []
        for item in items:
            gift_id = item.get('id') if isinstance(item, dict) else None
            if gift_id:
                try:
                    # Пробуем получить продажи через отдельный endpoint
                    if hasattr(requests, 'Session') and hasattr(requests.Session, 'impersonate'):
                        session = requests.Session(impersonate="chrome110")
                        response = session.get(
                            f"{MRKT_API_URL}/gifts/{gift_id}/sales",
                            headers=headers,
                            timeout=30
                        )
                    else:
                        response = requests.get(
                            f"{MRKT_API_URL}/gifts/{gift_id}/sales",
                            headers=headers,
                            timeout=30
                        )
                    
                    if response.status_code == 200:
                        sales_data = response.json()
                        if isinstance(sales_data, list):
                            for sale in sales_data:
                                sale['gift_id'] = gift_id  # Добавляем ID для ссылки
                                all_sales.append(sale)
                        elif isinstance(sales_data, dict):
                            sales_list = sales_data.get('sales', [])
                            for sale in sales_list:
                                sale['gift_id'] = gift_id
                                all_sales.append(sale)
                except Exception as e:
                    logger.debug(f"Could not get sales for gift {gift_id}: {e}")
                    continue
        
        # Убираем дубликаты и сортируем по дате
        seen = set()
        unique_sales = []
        for sale in all_sales:
            price = sale.get('price') or sale.get('amount') or sale.get('sale_price')
            date = sale.get('date') or sale.get('sold_at') or sale.get('created_at')
            key = (price, date)
            if key not in seen:
                seen.add(key)
                unique_sales.append(sale)
                if len(unique_sales) >= limit:
                    break
        
        return unique_sales[:limit]
    except Exception as e:
        logger.error(f"Error getting MRKT model sales history: {e}")
        return []


def get_mrkt_gift_by_id(gift_id: str, auth_token: str) -> Optional[Dict[str, Any]]:
    """
    Получение информации о подарке по ID в MRKT
    
    Args:
        gift_id: ID подарка (хеш)
        auth_token: Токен аутентификации
        
    Returns:
        Данные о подарке или None
    """
    try:
        headers = {
            "Authorization": auth_token,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Пробуем разные endpoints
        endpoints = [
            f"{MRKT_API_URL}/gifts/{gift_id}",
            f"{MRKT_API_URL}/nfts/{gift_id}",
        ]
        
        for endpoint in endpoints:
            try:
                if hasattr(requests, 'Session') and hasattr(requests.Session, 'impersonate'):
                    session = requests.Session(impersonate="chrome110")
                    response = session.get(endpoint, headers=headers, timeout=30)
                else:
                    response = requests.get(endpoint, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict):
                        return data
                elif response.status_code == 404:
                    continue  # Пробуем следующий endpoint
            except Exception as e:
                logger.debug(f"Error getting gift by id from {endpoint}: {e}")
                continue
        
        return None
    except Exception as e:
        logger.error(f"Error in get_mrkt_gift_by_id: {str(e)}")
        return None
