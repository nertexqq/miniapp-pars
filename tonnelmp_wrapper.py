"""
Обертка для работы с Tonnel Marketplace API через tonnelmp
"""

import logging
from typing import List, Dict, Optional, Any
import requests
import re
import json

logger = logging.getLogger(__name__)


def _normalize_image_url(url: str) -> str:
    """Нормализует URL изображения (включая ipfs:// и схемы без протокола)."""
    if not url:
        return url
    url = url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("ipfs://"):
        ipfs_path = url[len("ipfs://"):]
        if ipfs_path.startswith("ipfs/"):
            ipfs_path = ipfs_path[len("ipfs/"):]
        return f"https://ipfs.io/ipfs/{ipfs_path}"
    if url.startswith("ipfs/"):
        return f"https://ipfs.io/ipfs/{url[len('ipfs/'):]}"
    return url


def _extract_photo_url(item: Any) -> Optional[str]:
    """Пытается извлечь URL изображения из разных форматов ответа Tonnel."""
    if not isinstance(item, dict):
        return None
    image_keys = (
        "photo_url", "image_url", "image", "photo", "photoUrl", "imageUrl",
        "image_preview", "preview", "preview_url", "thumbnail", "thumb",
        "img", "image_src", "imageSrc",
    )
    list_keys = ("images", "previews", "photos", "media", "files")
    nested_keys = ("gift", "nft", "metadata", "meta", "data", "item", "gift_data", "asset")

    # Прямые ключи
    for key in image_keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_image_url(value)
        if isinstance(value, dict):
            for subkey in ("url", "src", "href"):
                subval = value.get(subkey)
                if isinstance(subval, str) and subval.strip():
                    return _normalize_image_url(subval)

    # Списки изображений
    for key in list_keys:
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and entry.strip():
                    return _normalize_image_url(entry)
                if isinstance(entry, dict):
                    for subkey in ("url", "src", "href"):
                        subval = entry.get(subkey)
                        if isinstance(subval, str) and subval.strip():
                            return _normalize_image_url(subval)

    # Вложенные объекты
    for key in nested_keys:
        value = item.get(key)
        if isinstance(value, dict):
            nested = _extract_photo_url(value)
            if nested:
                return nested

    # Последняя попытка — любая строка с URL
    for value in item.values():
        if isinstance(value, str) and value.strip():
            if value.startswith(("http://", "https://", "ipfs://", "//")):
                return _normalize_image_url(value)

    return None


def _build_fragment_photo_url(item: Any) -> Optional[str]:
    """Фолбек: формируем ссылку на фото через nft.fragment.com."""
    if not isinstance(item, dict):
        return None
    name = item.get("gift_name") or item.get("name") or ""
    gift_num = (
        item.get("external_collection_number")
        or item.get("gift_num")
        or item.get("number")
        or item.get("gift_number")
        or item.get("gift_id")
        or item.get("id")
    )
    if not name or not gift_num:
        return None
    slug = re.sub(r"[^a-z0-9]", "", str(name).lower())
    if not slug:
        return None
    return f"https://nft.fragment.com/gift/{slug}-{gift_num}.medium.jpg"


def _normalize_tonnel_key(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"\s+", " ", str(value))
    return value.strip().lower()


def _strip_tonnel_rarity(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s*\([^)]*\)", "", str(value)).strip()


def _find_tonnel_gift_data(data: Dict[str, Any], gift_name: str) -> Optional[Dict[str, Any]]:
    gift_key = _normalize_tonnel_key(gift_name)
    if not gift_key:
        return None
    if gift_key in data:
        gift_data = data.get(gift_key)
        return gift_data if isinstance(gift_data, dict) else None
    for key, value in data.items():
        if isinstance(key, str) and _normalize_tonnel_key(key) == gift_key:
            return value if isinstance(value, dict) else None
    return None

try:
    from tonnelmp import getGifts, saleHistory, filterStatsPretty, giftData
except ImportError:
    logger.error("tonnelmp not installed. Install it with: pip install tonnelmp")
    getGifts = None
    saleHistory = None
    filterStatsPretty = None
    giftData = None


def search_tonnel(
    gift_name: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 10,
    sort: str = "price_asc",
    authData: Optional[str] = None
) -> List[Dict[str, Any]] | str:
    """
    Поиск подарков в Tonnel Marketplace
    
    Args:
        gift_name: Название подарка
        model: Модель подарка
        limit: Максимальное количество результатов (максимум 30)
        sort: Тип сортировки (price_asc, price_desc, latest, mint_time, rarity, gift_id_asc, gift_id_desc)
        authData: Токен аутентификации Tonnel
        
    Returns:
        Список подарков или строка с ошибкой
    """
    # Если tonnelmp недоступен, используем прямой запрос к gifts2.tonnel.network/pageGifts
    if not getGifts:
        return _search_pagegifts(gift_name=gift_name, model=model, limit=limit, sort=sort, authData=authData)
    
    # authData опциональный согласно документации API, но рекомендуется для полного доступа
    # Если authData не передан, API может работать с ограничениями
    
    try:
        # Ограничиваем limit до максимум 30 (ограничение API)
        if limit > 30:
            logger.warning(f"Limit {limit} exceeds maximum of 30, using 30 instead")
            limit = 30
        if limit < 1:
            limit = 1
        
        # Маппинг сортировки - используем поддерживаемые значения API
        # Доступные: "price_asc", "price_desc", "latest", "mint_time", "rarity", "gift_id_asc", "gift_id_desc"
        sort_map = {
            "price_asc": "price_asc",
            "price_desc": "price_desc",
            "latest": "latest",  # API поддерживает "latest"
            "mint_time": "mint_time",
            "rarity": "rarity",
            "gift_id_asc": "gift_id_asc",
            "gift_id_desc": "gift_id_desc",
        }
        
        sort_value = sort_map.get(sort, "price_asc")
        
        # Формируем параметры для getGifts
        # Согласно документации, authData опциональный, но мы передаем его если он есть
        params = {
            "limit": limit,
            "sort": sort_value
        }
        
        # Добавляем authData только если он не пустой
        if authData and authData.strip():
            params["authData"] = authData.strip()
        
        # Добавляем gift_name и model только если они не None и не пустые
        if gift_name and gift_name.strip():
            params["gift_name"] = gift_name.strip()
        if model and model.strip():
            params["model"] = model.strip()
        
        # Выполняем поиск с retry для 429 ошибок
        params_str = ', '.join(f'{k}={v if k != "authData" else "***"}' for k, v in params.items())
        logger.debug(f"Calling getGifts with params: {params_str}")
        
        import time
        max_retries = 3
        retry_delay = 2  # Начальная задержка в секундах
        
        for attempt in range(max_retries):
            try:
                items = getGifts(**params)
                # Если успешно, выходим из цикла
                break
            except Exception as e:
                error_msg = str(e)
                
                # Если это ошибка подключения (Failed to connect), пробуем fallback метод
                if "Failed to connect" in error_msg or "Could not connect" in error_msg or "curl: (7)" in error_msg:
                    logger.warning(f"Tonnel API connection error, trying fallback method: {error_msg}")
                    if attempt < max_retries - 1:
                        # Пробуем использовать прямой запрос к API
                        try:
                            fallback_result = _search_pagegifts(gift_name=gift_name, model=model, limit=limit, sort=sort, authData=authData)
                            if isinstance(fallback_result, list):
                                logger.info(f"Fallback method succeeded, got {len(fallback_result)} items")
                                return fallback_result
                        except Exception as e2:
                            logger.debug(f"Fallback method also failed: {e2}")
                    
                    # Если это последняя попытка и fallback не сработал, ждем и пробуем еще раз
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (attempt + 1)
                        logger.warning(f"Tonnel API connection error, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"getGifts failed after {max_retries} retries due to connection error: {error_msg}")
                        # Пробуем fallback в последний раз
                        try:
                            return _search_pagegifts(gift_name=gift_name, model=model, limit=limit, sort=sort, authData=authData)
                        except:
                            return f"Error: tonnelmp: getGifts(): Connection failed after {max_retries} retries"
                
                # Если это 429 ошибка (Too Many Requests), ждем и повторяем
                if "429" in error_msg or "Too Many Requests" in error_msg or "CloudFlare" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Экспоненциальная задержка
                        logger.warning(f"Tonnel API rate limit (429), waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"getGifts failed after {max_retries} retries due to rate limit: {error_msg}")
                        return f"Error: tonnelmp: getGifts(): Request failed with status code 429 (Rate limit exceeded)"
                
                logger.error(f"getGifts raised exception: {error_msg}")
                
                # Если ошибка 400, пробуем разные варианты
                if "400" in error_msg or "Bad Request" in error_msg:
                    logger.info("Trying getGifts with different parameters")
                    
                    # Пробуем без gift_name и model, если они были переданы
                    if gift_name or model:
                        try:
                            minimal_params = {
                                "limit": limit,
                                "sort": sort_value
                            }
                            if authData and authData.strip():
                                minimal_params["authData"] = authData.strip()
                            logger.info("Trying getGifts without gift_name/model")
                            items = getGifts(**minimal_params)
                            logger.info("getGifts succeeded with minimal parameters")
                            break  # Успешно, выходим из цикла
                        except Exception as e2:
                            logger.error(f"getGifts failed even with minimal parameters: {e2}")
                            # Пробуем с дефолтными параметрами
                            try:
                                default_params = {
                                    "limit": 30,
                                    "sort": "price_asc"
                                }
                                if authData and authData.strip():
                                    default_params["authData"] = authData.strip()
                                logger.info("Trying getGifts with default parameters")
                                items = getGifts(**default_params)
                                logger.info("getGifts succeeded with default parameters")
                                break  # Успешно, выходим из цикла
                            except Exception as e3:
                                logger.error(f"getGifts failed with default parameters: {e3}")
                                return f"Error: tonnelmp: getGifts(): Request failed with status code 400"
                    else:
                        # Если уже были минимальные параметры, пробуем с дефолтными
                        try:
                            default_params = {
                                "limit": 30,
                                "sort": "price_asc"
                            }
                            if authData and authData.strip():
                                default_params["authData"] = authData.strip()
                            logger.info("Trying getGifts with default parameters")
                            items = getGifts(**default_params)
                            logger.info("getGifts succeeded with default parameters")
                            break  # Успешно, выходим из цикла
                        except Exception as e3:
                            logger.error(f"getGifts failed with default parameters: {e3}")
                            return f"Error: tonnelmp: getGifts(): Request failed with status code 400"
                else:
                    # Если не 400 и не 429, возвращаем ошибку после всех попыток
                    if attempt == max_retries - 1:
                        return f"Error: {error_msg}"
        
        if isinstance(items, str):
            logger.error(f"getGifts returned error string: {items}")
            return items
        
        if not isinstance(items, list):
            logger.warning(f"getGifts returned non-list type: {type(items)}, falling back to pageGifts")
            return _search_pagegifts(gift_name=gift_name, model=model, limit=limit, sort=sort, authData=authData)
        
        # Преобразуем формат для совместимости с Portals
        result = []
        for item in items:
            if isinstance(item, dict):
                # Преобразуем формат Tonnel в формат Portals
                photo_url = _extract_photo_url(item) or _build_fragment_photo_url(item)
                converted = {
                    'id': item.get('gift_id') or item.get('id'),
                    'name': item.get('gift_name') or item.get('name'),
                    'model': item.get('model') or item.get('model_name'),
                    'price': item.get('price') or item.get('raw_price', 0),
                    'floor_price': item.get('floor_price'),
                    'photo_url': photo_url,
                    'model_rarity': item.get('model_rarity') or item.get('rarity'),
                    'backdrop': item.get('backdrop'),
                    'pattern': item.get('pattern'),
                    'external_collection_number': item.get('external_collection_number') or item.get('gift_num') or item.get('number') or item.get('gift_number'),
                }
                result.append(converted)
        
        return result
    except Exception as e:
        logger.error(f"Error in search_tonnel: {e}")
        # Фолбек на прямой API
        try:
            return _search_pagegifts(gift_name=gift_name, model=model, limit=limit, sort=sort, authData=authData)
        except Exception as e2:
            logger.error(f"Fallback pageGifts failed: {e2}")
            return f"Error: {str(e)}"


def _search_pagegifts(
    gift_name: Optional[str],
    model: Optional[str],
    limit: int,
    sort: str,
    authData: Optional[str],
) -> List[Dict[str, Any]] | str:
    """
    Прямой запрос к https://gifts2.tonnel.network/api/pageGifts согласно документации
    https://github.com/boostNT/Tonnel-API
    """
    url = "https://gifts2.tonnel.network/api/pageGifts"
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://market.tonnel.network",
        "referer": "https://market.tonnel.network/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36",
    }

    # Ограничение API
    limit = max(1, min(limit, 30))

    # Маппинг сортировки в JSON-формат API
    sort_map = {
        "latest": {"message_post_time": -1, "gift_id": -1},
        "price_asc": {"price": 1},
        "price_desc": {"price": -1},
        "gift_id_asc": {"gift_id": 1},
        "gift_id_desc": {"gift_id": -1},
        "rarity": {"rarity": -1},
    }
    sort_json = sort_map.get(sort, {"message_post_time": -1, "gift_id": -1})

    # Базовый фильтр
    filter_data = {
        "price": {"$exists": True},
        "refunded": {"$ne": True},
        "buyer": {"$exists": False},
        "export_at": {"$exists": True},
        "asset": "TON",
    }
    if gift_name:
        filter_data["gift_name"] = gift_name
    if model:
        # Если модель содержит скобку (редкость), используем точное совпадение, иначе regex по началу
        if "(" in model and ")" in model:
            filter_data["model"] = model
        else:
            filter_data["model"] = {"$regex": f"^{model}"}

    json_data = {
        "page": 1,
        "limit": limit,
        "sort": json.dumps(sort_json, ensure_ascii=False),
        "filter": json.dumps(filter_data, ensure_ascii=False),
        "price_range": None,
        "user_auth": authData or "",
    }

    try:
        resp = requests.post(url, headers=headers, json=json_data, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"pageGifts request failed: {e}")
        return f"Error: {e}"

    # Ответ может быть списком или словарем
    items = data
    if isinstance(data, dict):
        if "items" in data:
            items = data.get("items") or []
        elif "data" in data:
            items = data.get("data") or []
        elif "results" in data:
            items = data.get("results") or []
        elif "gifts" in data:
            items = data.get("gifts") or []

    if not isinstance(items, list):
        logger.warning(f"pageGifts returned non-list: {type(items)}")
        return []

    result: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        try:
            if price and float(price) > 1e9:
                price = float(price) / 1e9
            elif price is not None:
                price = float(price)
        except Exception:
            pass
        photo_url = _extract_photo_url(item) or _build_fragment_photo_url(item)
        converted = {
            "id": item.get("gift_id") or item.get("id"),
            "name": item.get("gift_name") or item.get("name"),
            "model": item.get("model") or item.get("model_name"),
            "price": price,
            "floor_price": item.get("floor_price"),
            "photo_url": photo_url,
            "model_rarity": item.get("model_rarity") or item.get("rarity"),
            "backdrop": item.get("backdrop"),
            "pattern": item.get("pattern"),
            "external_collection_number": item.get("gift_num") or item.get("number") or item.get("external_collection_number"),
        }
        result.append(converted)

    return result


def get_tonnel_model_floor_price(gift_name: str, model: str, authData: str) -> Optional[float]:
    """
    Получение флор-цены для конкретной модели подарка в Tonnel
    Использует filterStatsPretty() из tonnelmp согласно документации:
    https://github.com/bleach-hub/tonnelmp
    
    Args:
        gift_name: Название подарка (не требует капитализации)
        model: Название модели (не требует капитализации, редкость включена в ключ)
        authData: Токен аутентификации
        
    Returns:
        Флор-цена модели или None
    """
    if not filterStatsPretty:
        logger.error("filterStatsPretty not available from tonnelmp")
        return None
    
    try:
        logger.info(f"get_tonnel_model_floor_price called for {gift_name} / {model}")
        
        # Получаем статистику через filterStatsPretty с retry для 429 ошибок
        import time
        max_retries = 3
        retry_delay = 2
        stats = None
        
        for attempt in range(max_retries):
            try:
                stats = filterStatsPretty(authData)
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg or "CloudFlare" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        logger.warning(f"Tonnel API rate limit (429) in filterStatsPretty, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"filterStatsPretty failed after {max_retries} retries due to rate limit")
                        return None
                else:
                    raise  # Пробрасываем другие ошибки
        
        if not isinstance(stats, dict) or stats.get('status') != 'success':
            logger.error(f"filterStatsPretty returned error: {stats}")
            return None
        
        data = stats.get('data', {})
        if not data:
            logger.warning("filterStatsPretty returned empty data")
            return None

        gift_key = _normalize_tonnel_key(gift_name)
        model_key_raw = _normalize_tonnel_key(model)
        model_key_clean = _normalize_tonnel_key(_strip_tonnel_rarity(model))

        logger.info(f"Looking for gift_key='{gift_key}', model_key='{model_key_raw}' in data")
        logger.debug(f"Available gift keys: {list(data.keys())[:10]}")

        gift_data = _find_tonnel_gift_data(data, gift_name)
        if gift_data and isinstance(gift_data, dict):
            logger.debug(f"Available model keys for {gift_key}: {list(gift_data.keys())[:10]}")

            model_info = None
            if model_key_raw in gift_data:
                model_info = gift_data[model_key_raw]
            elif model_key_clean in gift_data:
                model_info = gift_data[model_key_clean]

            if model_info is None:
                for key in gift_data.keys():
                    if not isinstance(key, str):
                        continue
                    key_norm = _normalize_tonnel_key(key)
                    key_clean = _normalize_tonnel_key(_strip_tonnel_rarity(key))
                    if key_norm == model_key_raw or key_clean == model_key_clean:
                        model_info = gift_data[key]
                        logger.info(f"Found model with key '{key}' matching '{model_key_raw}'")
                        break
                    if key_norm.startswith(model_key_clean) and model_key_clean:
                        model_info = gift_data[key]
                        logger.info(f"Found model with key '{key}' matching prefix '{model_key_clean}'")
                        break

            if model_info and isinstance(model_info, dict):
                floor_price = model_info.get('floorPrice')
                if floor_price is not None:
                    result = float(floor_price)
                    logger.info(f"get_tonnel_model_floor_price result: {result} TON")
                    return result
                else:
                    logger.warning(f"Model info found but no floorPrice: {model_info}")
            else:
                logger.warning(f"Model '{model_key_raw}' not found in gift '{gift_key}'")
        else:
            logger.warning(f"Gift '{gift_key}' not found in filterStatsPretty data")
        
        return None
    except Exception as e:
        logger.error(f"Error getting Tonnel model floor price: {e}", exc_info=True)
        return None


def get_tonnel_gift_floor_price(gift_name: str, authData: str) -> Optional[float]:
    """
    Получение флор-цены для подарка (все модели) в Tonnel
    
    Args:
        gift_name: Название подарка
        authData: Токен аутентификации
        
    Returns:
        Флор-цена подарка или None
    """
    if not filterStatsPretty:
        return None
    
    try:
        # Получаем статистику через filterStatsPretty с retry для 429 ошибок
        import time
        max_retries = 3
        retry_delay = 2
        stats = None
        
        for attempt in range(max_retries):
            try:
                stats = filterStatsPretty(authData)
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg or "CloudFlare" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        logger.warning(f"Tonnel API rate limit (429) in filterStatsPretty, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"filterStatsPretty failed after {max_retries} retries due to rate limit")
                        return None
                else:
                    raise  # Пробрасываем другие ошибки
        
        if not isinstance(stats, dict) or stats.get('status') != 'success':
            return None
        
        data = stats.get('data', {})
        if not data:
            return None

        gift_data = _find_tonnel_gift_data(data, gift_name)
        if gift_data and isinstance(gift_data, dict):
            gift_info = gift_data.get('data')
            if isinstance(gift_info, dict):
                floor_price = gift_info.get('floorPrice')
                if floor_price is not None:
                    return float(floor_price)
        
        return None
    except Exception as e:
        logger.error(f"Error getting Tonnel gift floor price: {e}")
        return None


def get_tonnel_model_sales_history(gift_name: str, model: str, authData: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Получение истории продаж для модели подарка в Tonnel
    
    Args:
        gift_name: Название подарка
        model: Название модели
        authData: Токен аутентификации
        limit: Количество последних продаж
        
    Returns:
        Список продаж модели (отсортированный по дате, самые последние первыми)
    """
    if not saleHistory:
        return []
    
    try:
        # Берем больше продаж для фильтрации по модели
        # Увеличиваем limit в 5 раз, чтобы точно найти нужное количество продаж модели
        import time
        max_retries = 3
        retry_delay = 2
        sales = None
        
        for attempt in range(max_retries):
            try:
                sales = saleHistory(
                    authData=authData,
                    page=1,
                    limit=limit * 5,  # Берем больше для фильтрации
                    type="SALE",
                    gift_name=gift_name,
                    model=model,
                    sort="latest"
                )
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg or "CloudFlare" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        logger.warning(f"Tonnel API rate limit (429) in saleHistory, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"saleHistory failed after {max_retries} retries due to rate limit")
                        return []
                else:
                    raise  # Пробрасываем другие ошибки
        
        if not isinstance(sales, list):
            return []
        
        # Очищаем названия для точного сравнения
        gift_name_clean = re.sub(r'\s*\([^)]*\)', '', gift_name).strip().lower()
        model_clean = re.sub(r'\s*\([^)]*\)', '', model).strip().lower()
        
        # Фильтруем по модели и подарку, сортируем по дате (самые последние первыми)
        filtered = []
        for sale in sales:
            if isinstance(sale, dict):
                sale_gift_name = sale.get('gift_name') or sale.get('name') or ''
                sale_model = sale.get('model') or sale.get('model_name') or ''
                
                # Очищаем от редкости в скобках для сравнения
                sale_gift_name_clean = re.sub(r'\s*\([^)]*\)', '', sale_gift_name).strip().lower()
                sale_model_clean = re.sub(r'\s*\([^)]*\)', '', sale_model).strip().lower()
                
                # Точное сравнение по названию подарка и модели
                if sale_gift_name_clean == gift_name_clean and sale_model_clean == model_clean:
                    filtered.append(sale)
                    if len(filtered) >= limit:
                        break
        
        # Сортируем по дате (самые последние первыми)
        def get_sale_timestamp(sale):
            sale_date = sale.get('date') or sale.get('sold_at') or sale.get('created_at') or sale.get('timestamp') or 0
            if isinstance(sale_date, (int, float)):
                return sale_date
            elif isinstance(sale_date, str):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(sale_date.replace('Z', '+00:00'))
                    return dt.timestamp()
                except:
                    return 0
            return 0
        
        filtered.sort(key=get_sale_timestamp, reverse=True)
        
        return filtered[:limit]
    except Exception as e:
        logger.error(f"Error getting Tonnel model sales history: {e}", exc_info=True)
        return []


def get_tonnel_gift_sales_history(gift_name: str, authData: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Получение истории продаж для подарка (все модели) в Tonnel
    
    Args:
        gift_name: Название подарка
        authData: Токен аутентификации
        limit: Количество последних продаж
        
    Returns:
        Список продаж подарка
    """
    if not saleHistory:
        return []
    
    try:
        # Получаем историю продаж с retry для 429 ошибок
        import time
        max_retries = 3
        retry_delay = 2
        sales = None
        
        for attempt in range(max_retries):
            try:
                sales = saleHistory(
                    authData=authData,
                    page=1,
                    limit=limit * 2,  # Берем больше для фильтрации
                    type="SALE",
                    gift_name=gift_name,
                    sort="latest"
                )
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg or "CloudFlare" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        logger.warning(f"Tonnel API rate limit (429) in saleHistory, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"saleHistory failed after {max_retries} retries due to rate limit")
                        return []
                else:
                    raise  # Пробрасываем другие ошибки
        
        if not isinstance(sales, list):
            return []
        
        # Фильтруем по подарку и берем последние limit
        filtered = []
        for sale in sales:
            if isinstance(sale, dict):
                sale_gift_name = (sale.get('gift_name') or sale.get('name') or '').lower()
                
                if sale_gift_name == gift_name.lower():
                    filtered.append(sale)
                    if len(filtered) >= limit:
                        break
        
        return filtered[:limit]
    except Exception as e:
        logger.error(f"Error getting Tonnel gift sales history: {e}")
        return []


def get_tonnel_gift_by_id(gift_id: str, authData: str) -> Optional[Dict[str, Any]]:
    """
    Получение информации о подарке по ID в Tonnel
    
    Args:
        gift_id: ID подарка
        authData: Токен аутентификации
        
    Returns:
        Данные о подарке или None (в нормализованном формате)
    """
    if not giftData:
        return None
    
    try:
        data = giftData(gift_id=int(gift_id) if gift_id.isdigit() else gift_id, authData=authData)
        if isinstance(data, dict):
            # Нормализуем формат как в search_tonnel
            normalized = {
                'id': data.get('gift_id') or data.get('id'),
                'name': data.get('gift_name') or data.get('name'),
                'model': data.get('model') or data.get('model_name'),
                'price': data.get('price') or data.get('raw_price', 0),
                'floor_price': data.get('floor_price') or data.get('price', 0),
                'photo_url': data.get('photo_url') or data.get('image_url') or data.get('image'),
                'model_rarity': data.get('model_rarity') or data.get('rarity'),
                'backdrop': data.get('backdrop'),
                'pattern': data.get('pattern'),
                'external_collection_number': data.get('external_collection_number') or data.get('gift_num') or data.get('number') or data.get('gift_number'),
            }
            return normalized
        return None
    except Exception as e:
        logger.error(f"Error getting Tonnel gift by id: {e}")
        return None

