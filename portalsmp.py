"""
Модуль для работы с Portals Market API
"""

try:
    # Используем curl_cffi для лучшей совместимости (как в официальной библиотеке)
    from curl_cffi import requests
except ImportError:
    # Fallback на обычный requests если curl_cffi не установлен
    import requests

import logging
import re
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# API URL как в официальной библиотеке portalsmp
PORTALS_API_URL = 'https://portal-market.com/api/'


async def update_auth(api_id: int, api_hash: str) -> Optional[str]:
    """
    Обновляет токен аутентификации для работы с Portals API
    Пробует разные API endpoints если основной не работает
    
    Args:
        api_id: API ID от Telegram
        api_hash: API Hash от Telegram
        
    Returns:
        Токен аутентификации или None в случае ошибки
    """
    # Используем правильный API URL
    try:
        logger.info(f"Trying authentication at {PORTALS_API_URL}")
        # Используем curl_cffi с правильными заголовками как в официальной библиотеке
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://portal-market.com",
            "Referer": "https://portal-market.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }
        # Используем curl_cffi если доступен
        try:
            response = requests.post(
                f"{PORTALS_API_URL}auth",
                json={"api_id": api_id, "api_hash": api_hash},
                headers=headers,
                timeout=30,
                impersonate="chrome110"  # curl_cffi feature для имитации браузера
            )
        except TypeError:
            # Если impersonate не поддерживается (обычный requests)
            response = requests.post(
                f"{PORTALS_API_URL}auth",
                json={"api_id": api_id, "api_hash": api_hash},
                headers=headers,
                timeout=30
            )
            
        if response.status_code == 200:
            data = response.json()
            
            if "token" in data:
                logger.info(f"Auth successful")
                return data["token"]
            elif "auth_token" in data:
                logger.info(f"Auth successful")
                return data["auth_token"]
            elif "access_token" in data:
                logger.info(f"Auth successful")
                return data["access_token"]
            else:
                logger.error(f"Unexpected auth response format: {data}")
                return None
        else:
            logger.error(f"Auth failed with status {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error during auth: {e}")
        return None
    except Exception as e:
        logger.error(f"Error during auth: {e}")
        return None


def search(
    gift_name: Optional[List[str]] | str = None,
    model: Optional[List[str]] | str = None,
    limit: int = 10,
    sort: str = "price_asc",
    authData: Optional[str] = None
) -> List[Dict[str, Any]] | str:
    """
    Поиск подарков в Portals Market (как в официальной библиотеке portalsmp)
    
    Args:
        gift_name: Название подарка (строка) или список названий
        model: Модель (строка) или список моделей
        limit: Максимальное количество результатов
        sort: Тип сортировки (price_asc, price_desc, etc.)
        authData: Токен аутентификации
        
    Returns:
        Список подарков или строка с ошибкой
    """
    from urllib.parse import quote_plus
    import re
    
    def cap(text: str) -> str:
        words = re.findall(r"\w+(?:'\w+)?", text)
        for word in words:
            if len(word) > 0:
                cap_word = word[0].upper() + word[1:]
                text = text.replace(word, cap_word, 1)
        return text
    
    def listToURL(gifts: list) -> str:
        return '%2C'.join(quote_plus(cap(gift)) for gift in gifts)
    
    try:
        SORTS = {
            "latest": "&sort_by=listed_at+desc&status=listed&exclude_bundled=true&premarket_status=all",
            "price_asc": "&sort_by=price+asc",
            "price_desc": "&sort_by=price+desc",
            "gift_id_asc": "&sort_by=external_collection_number+asc",
            "gift_id_desc": "&sort_by=external_collection_number+desc",
            "model_rarity_asc": "&sort_by=model_rarity+asc",
            "model_rarity_desc": "&sort_by=model_rarity+desc"
        }
        
        URL = f"{PORTALS_API_URL}nfts/search?offset=0&limit={limit}{SORTS.get(sort, SORTS['price_asc'])}"
        
        if gift_name:
            if isinstance(gift_name, str):
                URL += f"&filter_by_collections={quote_plus(cap(gift_name))}"
            elif isinstance(gift_name, list):
                URL += f"&filter_by_collections={listToURL(gift_name)}"
        
        if model:
            if isinstance(model, str):
                URL += f"&filter_by_models={quote_plus(cap(model))}"
            elif isinstance(model, list):
                URL += f"&filter_by_models={listToURL(model)}"
        
        logger.info(f"Portals search URL: {URL[:200]}...")  # Логируем первые 200 символов URL
        
        # Если токен уже содержит "tma ", используем его как есть, иначе добавляем префикс
        auth_header = authData if authData and authData.startswith('tma ') else (f"tma {authData}" if authData else "")
        
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://portal-market.com",
            "Referer": "https://portal-market.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        }
        
        # Используем curl_cffi если доступен (лучше работает с DNS)
        try:
            # Проверяем, есть ли метод impersonate (curl_cffi)
            if hasattr(requests, 'get') and callable(getattr(requests, 'get', None)):
                # Пробуем использовать curl_cffi с impersonate
                try:
                    response = requests.get(URL, headers=headers, timeout=30, impersonate="chrome110")
                except (TypeError, AttributeError):
                    # Если impersonate не поддерживается, пробуем без него
                    response = requests.get(URL, headers=headers, timeout=30)
            else:
                # Обычный requests
                response = requests.get(URL, headers=headers, timeout=30)
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error making request to Portals API: {error_str}")
            
            # Если это ошибка DNS или curl, пробуем обычный requests
            if "Could not resolve host" in error_str or "curl" in error_str.lower() or "DNS" in error_str:
                logger.info("DNS/curl error detected, trying standard requests library")
                try:
                    import requests as std_requests
                    response = std_requests.get(URL, headers=headers, timeout=30)
                    logger.info(f"Standard requests succeeded: status={response.status_code}")
                except Exception as e2:
                    logger.error(f"Error with standard requests: {e2}")
                    return f"Error: Failed to perform, {str(e2)}"
            else:
                return f"Error: Failed to perform, {error_str}"
        
        if response.status_code == 401:
            return "Auth error: invalid or expired token"
        response.raise_for_status()
        
        data = response.json()
        logger.info(f"API response status: {response.status_code}, type: {type(data)}")
        if isinstance(data, dict):
            logger.info(f"API response keys: {list(data.keys())}")
        logger.debug(f"API response content: {str(data)[:500]}")
        
        # Возвращаем список напрямую (как в официальной библиотеке)
        if isinstance(data, dict):
            # Проверяем различные возможные ключи
            if "results" in data:
                results = data["results"]
                if isinstance(results, list):
                    # Нормализуем данные: извлекаем модель и редкость из attributes
                    normalized_results = []
                    for item in results:
                        if isinstance(item, dict):
                            # Извлекаем модель из attributes
                            model = None
                            model_rarity = None
                            if "attributes" in item and isinstance(item["attributes"], list):
                                for attr in item["attributes"]:
                                    if isinstance(attr, dict) and attr.get("type") == "model":
                                        model = attr.get("value")
                                        rarity_per_mille = attr.get("rarity_per_mille")
                                        if rarity_per_mille is not None:
                                            model_rarity = f"{rarity_per_mille}%"
                                        break
                            
                            # Добавляем нормализованные поля
                            normalized_item = item.copy()
                            if model:
                                normalized_item["model"] = model
                            if model_rarity:
                                normalized_item["model_rarity"] = model_rarity
                            
                            normalized_results.append(normalized_item)
                        else:
                            normalized_results.append(item)
                    
                    return normalized_results if normalized_results else []
                else:
                    logger.warning(f"Unexpected 'results' type: {type(results)}")
                    return []
            elif "items" in data:
                items = data["items"]
                if isinstance(items, list):
                    return items if items else []
                else:
                    logger.warning(f"Unexpected 'items' type: {type(items)}")
                    return []
            elif "data" in data:
                data_content = data["data"]
                if isinstance(data_content, list):
                    return data_content if data_content else []
                elif isinstance(data_content, dict) and "results" in data_content:
                    return data_content["results"] if data_content["results"] else []
                else:
                    logger.warning(f"Unexpected 'data' type: {type(data_content)}")
                    return []
            else:
                # Если это словарь, но нет известных ключей, логируем и возвращаем пустой список
                logger.warning(f"Unexpected dict structure. Keys: {list(data.keys())}")
                return []
        elif isinstance(data, list):
            return data if data else []
        else:
            logger.warning(f"Unexpected response type: {type(data)}, value: {str(data)[:200]}")
            return []
    except requests.exceptions.HTTPError as e:
        return f"HTTP error: {e.response.status_code}"
    except Exception as e:
        logger.error(f"Error in search: {e}")
        return f"Error: {str(e)}"


def filterFloors(
    items: List[Dict[str, Any]],
    min_floor_price: Optional[float] = None,
    max_floor_price: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Фильтрация подарков по флор-цене
    
    Args:
        items: Список подарков для фильтрации
        min_floor_price: Минимальная флор-цена
        max_floor_price: Максимальная флор-цена
        
    Returns:
        Отфильтрованный список подарков
    """
    filtered = items
    
    if min_floor_price is not None:
        filtered = [item for item in filtered if item.get("floor_price", 0) >= min_floor_price]
    
    if max_floor_price is not None:
        filtered = [item for item in filtered if item.get("floor_price", float('inf')) <= max_floor_price]
    
    return filtered


async def search_by_id(gift_id: str, auth_token: str):
    """
    Поиск подарка по ID
    
    Args:
        gift_id: ID подарка
        auth_token: Токен аутентификации
        
    Returns:
        Данные о подарке или None в случае ошибки
    """
    try:
        # Убираем префикс "gift_" если есть
        clean_id = gift_id.split('_')[-1] if '_' in gift_id else gift_id
        
        headers = {
            "Authorization": auth_token if auth_token and auth_token.startswith('tma ') else (f"tma {auth_token}" if auth_token else ""),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://portal-market.com",
            "Referer": "https://portal-market.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        }
        
        try:
            if hasattr(requests, 'Session') and hasattr(requests.Session, 'impersonate'):
                response = requests.get(
                    f"{PORTALS_API_URL}nfts/{clean_id}",
                    headers=headers,
                    timeout=30,
                    impersonate="chrome110"
                )
            else:
                response = requests.get(
                    f"{PORTALS_API_URL}nfts/{clean_id}",
                    headers=headers,
                    timeout=30
                )
        except (TypeError, AttributeError):
            response = requests.get(
                f"{PORTALS_API_URL}nfts/{clean_id}",
                headers=headers,
                timeout=30
            )
        
        if response.status_code == 401:
            return None
        response.raise_for_status()
        data = response.json()
        logger.debug(f"API response for gift_id={gift_id}: {type(data)}")
        return data
    except Exception as e:
        logger.error(f"Error in search_by_id: {str(e)}")
        return None


async def get_model_floor_price(gift_name: str, model: str, auth_token: str) -> Optional[float]:
    """
    Получение флор-цены для конкретной модели подарка
    Использует filterFloors() из aportalsmp согласно документации:
    https://bleach-1.gitbook.io/aportalsmp
    
    Args:
        gift_name: Название подарка (без редкости в скобках)
        model: Название модели (без редкости в скобках)
        auth_token: Токен аутентификации
        
    Returns:
        Флор-цена модели или None
    """
    try:
        logger.info(f"get_model_floor_price called for '{gift_name}' / '{model}'")
        
        # Очищаем модель от редкости в скобках для поиска
        model_clean = re.sub(r"\s*\([^)]*\)", "", model).strip() if model else ""
        
        # Пробуем использовать aportalsmp.filterFloors если доступен
        try:
            from aportalsmp.gifts import filterFloors
            
            # Используем filterFloors согласно документации
            filters = await filterFloors(gift_name=gift_name, authData=auth_token)
            
            # Получаем флор модели через метод .model()
            # Пробуем сначала с оригинальной моделью, потом с очищенной
            model_floor = None
            for model_to_try in [model, model_clean]:
                if not model_to_try:
                    continue
                try:
                    model_floor = filters.model(model_to_try)
                    if model_floor is not None:
                        break
                except Exception:
                    continue
            
            if model_floor is not None:
                result = float(model_floor)
                logger.info(f"get_model_floor_price result from filterFloors: {result} TON")
                return result
            else:
                logger.warning(f"filterFloors.model() returned None for gift '{gift_name}' / model '{model}'")
                # Пробуем найти модель в .models dict
                if hasattr(filters, 'models') and filters.models:
                    model_lower = model_clean.lower()
                    for model_name, floor_price in filters.models.items():
                        model_name_clean = re.sub(r"\s*\([^)]*\)", "", model_name).strip().lower()
                        if model_name_clean == model_lower or model_name.lower() == model_lower:
                            result = float(floor_price)
                            logger.info(f"get_model_floor_price result from filters.models: {result} TON (matched '{model_name}')")
                            return result
                    logger.warning(f"Model '{model}' not found in filters.models. Available models: {list(filters.models.keys())[:10]}")
        except ImportError:
            logger.info("aportalsmp.filterFloors not available, using search() fallback")
        except Exception as e:
            logger.warning(f"Error using filterFloors: {e}, trying search() fallback", exc_info=True)
        
        # Fallback на search() если filterFloors не доступен или не сработал
        items = search(
            gift_name=gift_name,
            model=model_clean if model_clean else model,
            limit=100,
            sort="price_asc",
            authData=auth_token
        )
        
        logger.info(f"search() returned: type={type(items)}, is_str={isinstance(items, str)}, is_list={isinstance(items, list)}, len={len(items) if isinstance(items, list) else 'N/A'}")
        
        if isinstance(items, str):
            logger.error(f"search() returned error string: {items}")
            return None
            
        if not isinstance(items, list):
            logger.error(f"search() returned non-list type: {type(items)}")
            return None
            
        if not items:
            logger.warning(f"No items found for '{gift_name}' / '{model}'")
            return None
        
        # Находим минимальную цену (флор)
        prices = []
        for item in items:
            if isinstance(item, dict):
                price = item.get('price') or item.get('floor_price')
            elif hasattr(item, 'price'):
                price = item.price
            elif hasattr(item, '__dict__'):
                price = getattr(item, 'price', None)
            else:
                continue
            
            if price is not None:
                try:
                    price_float = float(price)
                    if price_float > 0:
                        prices.append(price_float)
                except (ValueError, TypeError):
                    continue
        
        if prices:
            result = min(prices)
            logger.info(f"get_model_floor_price result from search: {result} TON (from {len(prices)} prices)")
            return result
        else:
            logger.warning(f"No valid prices found in {len(items)} items")
            return None
    except Exception as e:
        logger.error(f"Error getting model floor price: {e}", exc_info=True)
        return None


def get_gift_floor_price(gift_name: str, auth_token: str) -> Optional[float]:
    """
    Получение флор-цены для подарка (все модели)
    Использует filterFloors() из aportalsmp для получения флора коллекции
    
    Args:
        gift_name: Название подарка (без редкости в скобках)
        auth_token: Токен аутентификации
        
    Returns:
        Флор-цена подарка или None
    """
    try:
        logger.info(f"get_gift_floor_price called for '{gift_name}'")
        
        # Пробуем использовать aportalsmp.filterFloors если доступен
        try:
            import asyncio
            from aportalsmp.gifts import filterFloors
            
            # filterFloors - асинхронная функция
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если event loop уже запущен, используем run_coroutine_threadsafe или fallback
                    filters = None
                else:
                    filters = loop.run_until_complete(filterFloors(gift_name=gift_name, authData=auth_token))
            except RuntimeError:
                # Если нет event loop, создаем новый
                filters = asyncio.run(filterFloors(gift_name=gift_name, authData=auth_token))
            
            if filters:
                # Получаем флор всей коллекции
                # filterFloors возвращает объект, у которого может быть метод для получения флора коллекции
                # Или можно получить все модели и найти минимальную цену
                gift_floor = None
                
                # Пробуем разные методы для получения флора коллекции
                methods_to_try = ['all', 'collection', 'gift', 'floor', 'min']
                for method_name in methods_to_try:
                    if hasattr(filters, method_name):
                        try:
                            method = getattr(filters, method_name)
                            if callable(method):
                                gift_floor = method()
                            else:
                                gift_floor = method
                            if gift_floor is not None:
                                break
                        except Exception as e:
                            logger.debug(f"Method {method_name}() failed: {e}")
                            continue
                
                # Если методы не сработали, пробуем получить минимальную цену из всех моделей
                if gift_floor is None and hasattr(filters, 'models'):
                    try:
                        models_dict = filters.models
                        if models_dict:
                            all_floors = [float(v) for v in models_dict.values() if v is not None]
                            if all_floors:
                                gift_floor = min(all_floors)
                                logger.debug(f"Got gift floor from min of all models: {gift_floor}")
                    except Exception as e:
                        logger.debug(f"Error getting min from models: {e}")
                
                if gift_floor is not None:
                    result = float(gift_floor)
                    logger.info(f"get_gift_floor_price result from filterFloors: {result} TON")
                    return result
                else:
                    logger.warning(f"filterFloors methods returned None for gift '{gift_name}', available attributes: {dir(filters)[:20]}")
        except ImportError:
            logger.info("aportalsmp.filterFloors not available, using search() fallback")
        except Exception as e:
            logger.warning(f"Error using filterFloors: {e}, trying search() fallback", exc_info=True)
        
        # Fallback на search() если filterFloors не доступен или не сработал
        items = search(
            gift_name=gift_name,
            model=None,
            limit=100,
            sort="price_asc",
            authData=auth_token
        )
        
        logger.debug(f"get_gift_floor_price: search returned type: {type(items)}")
        
        # Обрабатываем разные форматы ответа
        if isinstance(items, str):
            logger.warning(f"get_gift_floor_price: search returned error string: {items}")
            return None
        
        if isinstance(items, dict):
            # Если dict, извлекаем results или items
            if 'results' in items:
                items = items.get('results') or []
                logger.debug(f"get_gift_floor_price: extracted {len(items)} items from 'results'")
            elif 'items' in items:
                items = items.get('items') or []
                logger.debug(f"get_gift_floor_price: extracted {len(items)} items from 'items'")
            else:
                logger.warning(f"get_gift_floor_price: dict without results/items: {list(items.keys())}")
                return None
        
        if not isinstance(items, list):
            logger.warning(f"get_gift_floor_price: items is not a list: {type(items)}")
            return None
            
        if not items:
            logger.warning(f"get_gift_floor_price: no items found for '{gift_name}'")
            return None
        
        logger.debug(f"get_gift_floor_price: processing {len(items)} items")
        
        # Находим минимальную цену (флор)
        prices = []
        for item in items:
            if isinstance(item, dict):
                price = item.get('price') or item.get('floor_price')
            elif hasattr(item, 'price'):
                price = item.price
            elif hasattr(item, '__dict__'):
                price = getattr(item, 'price', None)
            else:
                continue
            
            if price is not None:
                try:
                    price_float = float(price)
                    if price_float > 0:
                        prices.append(price_float)
                except (ValueError, TypeError):
                    continue
        
        if prices:
            result = min(prices)
            logger.info(f"get_gift_floor_price result: {result} TON (from {len(prices)} valid prices out of {len(items)} items)")
            return result
        else:
            logger.warning(f"get_gift_floor_price: no valid prices found in {len(items)} items")
            return None
    except Exception as e:
        logger.error(f"Error getting gift floor price: {e}", exc_info=True)
        return None


def get_model_sales_history(gift_name: str, model: str, auth_token: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Получение истории продаж для модели подарка (не конкретного экземпляра)
    
    Args:
        gift_name: Название подарка
        model: Название модели
        auth_token: Токен аутентификации
        limit: Количество последних продаж
        
    Returns:
        Список продаж модели
    """
    try:
        # Получаем все подарки этой модели
        items = search(
            gift_name=gift_name,
            model=model,
            limit=50,
            sort="latest",
            authData=auth_token
        )
        
        if isinstance(items, str) or not isinstance(items, list):
            return []
        
        # Собираем все продажи из всех подарков этой модели
        all_sales = []
        for item in items:
            gift_id = None
            if isinstance(item, dict):
                gift_id = item.get('id') or item.get('gift_id') or item.get('nft_id')
            elif hasattr(item, 'id'):
                gift_id = item.id
            
            if gift_id:
                # Получаем продажи для каждого подарка
                sales = get_sales_history(str(gift_id), auth_token, limit=10)
                all_sales.extend(sales)
        
        # Сортируем по дате (новые первые) и берем последние limit
        def get_sale_date(sale):
            date = sale.get('date') or sale.get('sold_at') or sale.get('created_at') or sale.get('timestamp') or 0
            if isinstance(date, str):
                try:
                    from datetime import datetime
                    return datetime.fromisoformat(date.replace('Z', '+00:00')).timestamp()
                except:
                    return 0
            return float(date) if date else 0
        
        all_sales.sort(key=get_sale_date, reverse=True)
        
        # Убираем дубликаты по цене и дате
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
        logger.error(f"Error getting model sales history: {e}")
        return []


def get_sales_history(gift_id: str, auth_token: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Получение истории продаж подарка
    
    Args:
        gift_id: ID подарка
        auth_token: Токен аутентификации
        limit: Количество последних продаж
        
    Returns:
        Список продаж или пустой список в случае ошибки
    """
    try:
        # Убираем префикс "gift_" если есть
        clean_id = gift_id.split('_')[-1] if '_' in gift_id else gift_id
        
        headers = {
            "Authorization": auth_token if auth_token and auth_token.startswith('tma ') else (f"tma {auth_token}" if auth_token else ""),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://portal-market.com",
            "Referer": "https://portal-market.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        }
        
        # Пробуем разные возможные endpoints для истории продаж
        endpoints = [
            f"{PORTALS_API_URL}nfts/{clean_id}/sales",
            f"{PORTALS_API_URL}nfts/{clean_id}/history",
            f"{PORTALS_API_URL}sales?nft_id={clean_id}",
            f"{PORTALS_API_URL}nft/{clean_id}/sales",
        ]
        
        for endpoint in endpoints:
            try:
                if hasattr(requests, 'Session') and hasattr(requests.Session, 'impersonate'):
                    response = requests.get(
                        endpoint,
                        headers=headers,
                        timeout=30,
                        impersonate="chrome110"
                    )
                else:
                    response = requests.get(
                        endpoint,
                        headers=headers,
                        timeout=30
                    )
                
                if response.status_code == 200:
                    data = response.json()
                    # Обрабатываем различные форматы ответа
                    if isinstance(data, list):
                        return data[:limit] if len(data) > limit else data
                    elif isinstance(data, dict):
                        if "sales" in data:
                            sales = data["sales"]
                            if isinstance(sales, list):
                                return sales[:limit] if len(sales) > limit else sales
                        elif "results" in data:
                            results = data["results"]
                            if isinstance(results, list):
                                return results[:limit] if len(results) > limit else results
                        elif "data" in data:
                            data_content = data["data"]
                            if isinstance(data_content, list):
                                return data_content[:limit] if len(data_content) > limit else data_content
                    return []
                elif response.status_code == 404:
                    # Endpoint не найден, пробуем следующий
                    continue
            except Exception as e:
                logger.debug(f"Error trying endpoint {endpoint}: {e}")
                continue
        
        logger.warning(f"Could not find sales history endpoint for gift_id={gift_id}")
        return []
    except Exception as e:
        logger.error(f"Error in get_sales_history: {str(e)}")
        return []

