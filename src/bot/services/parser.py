"""
Сервис для парсинга подарков с маркетплейсов
"""

import asyncio
import inspect
import logging
from typing import Set, List, Dict, Any, Optional
from ..config import settings

logger = logging.getLogger(__name__)

# Импорты маркетплейсов
try:
    from aportalsmp import search, update_auth
except ImportError:
    try:
        from portalsmp import search, update_auth
    except ImportError:
        search = None
        update_auth = None

try:
    from tonnelmp_wrapper import search_tonnel
except ImportError:
    search_tonnel = None

try:
    from mrktmp_wrapper import search_mrkt
except ImportError:
    search_mrkt = None

try:
    from getgems_wrapper import search_getgems
except ImportError:
    search_getgems = None


class ParserService:
    """Сервис для парсинга подарков"""
    
    def __init__(self, cache_service):
        self.cache = cache_service
        self.auth_token = None
    
    async def get_all_gift_names_from_marketplace(self, marketplace: str) -> Set[str]:
        """Получить все уникальные названия подарков с маркетплейса"""
        cache_key = f"gift_names:{marketplace}"
        
        # Проверяем кеш
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return set(cached)
        
        gift_names = set()
        
        try:
            if marketplace == 'portals' and search:
                gift_names = await self._get_portals_gift_names()
            elif marketplace == 'tonnel' and search_tonnel:
                gift_names = await self._get_tonnel_gift_names()
            elif marketplace == 'mrkt' and search_mrkt:
                gift_names = await self._get_mrkt_gift_names()
            elif marketplace == 'getgems' and search_getgems:
                gift_names = await self._get_getgems_gift_names()
        except Exception as e:
            logger.error(f"Error getting gift names from {marketplace}: {e}", exc_info=True)
        
        # Сохраняем в кеш
        await self.cache.set(cache_key, list(gift_names), ttl=600)  # 10 минут
        
        return gift_names
    
    async def _get_portals_gift_names(self) -> Set[str]:
        """Получить названия подарков с Portals"""
        gift_names = set()
        
        try:
            # Инициализируем auth если нужно
            if not self.auth_token:
                if update_auth:
                    if inspect.iscoroutinefunction(update_auth):
                        self.auth_token = await update_auth(settings.API_ID, settings.API_HASH)
                    else:
                        self.auth_token = await asyncio.to_thread(update_auth, settings.API_ID, settings.API_HASH)
            
            portals_auth = settings.PORTALS_AUTH if settings.PORTALS_AUTH else self.auth_token
            
            if not portals_auth:
                logger.warning("No Portals auth token available")
                return gift_names
            
            # Получаем коллекции через API
            try:
                import requests as req_lib
                try:
                    from curl_cffi import requests as curl_requests
                    requests_lib = curl_requests
                except ImportError:
                    requests_lib = req_lib
                
                from portalsmp import PORTALS_API_URL
                collections_url = f"{PORTALS_API_URL}collections?limit=1000"
                headers = {
                    "Authorization": portals_auth if portals_auth.startswith('tma ') else f"tma {portals_auth}",
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://portal-market.com",
                    "Referer": "https://portal-market.com/",
                }
                
                if hasattr(requests_lib, 'Session') and hasattr(requests_lib.Session, 'impersonate'):
                    session = requests_lib.Session(impersonate="chrome110")
                    response = session.get(collections_url, headers=headers, timeout=30)
                else:
                    response = requests_lib.get(collections_url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    collections = data.get('collections') or data.get('results') or []
                    
                    for collection in collections:
                        if isinstance(collection, dict):
                            name = collection.get('name') or collection.get('collectionName')
                            if name:
                                gift_names.add(name)
                    
                    logger.info(f"[gifts] Portals: Got {len(collections)} collections from API")
            except Exception as e:
                logger.warning(f"[gifts] Portals: Error getting collections: {e}")
            
            # Дополнительно получаем через поиск (упрощенная версия)
            if search:
                try:
                    limit = 100
                    offset = 0
                    seen_names = set(gift_names)
                    
                    for _ in range(10):  # Максимум 1000 подарков
                        if inspect.iscoroutinefunction(search):
                            items = await search(limit=limit, offset=offset, sort="price_asc", authData=portals_auth)
                        else:
                            items = await asyncio.to_thread(search, limit=limit, offset=offset, sort="price_asc", authData=portals_auth)
                        
                        if isinstance(items, dict):
                            items = items.get('results') or items.get('items') or []
                        elif not isinstance(items, list):
                            break
                        
                        if not items:
                            break
                        
                        for item in items:
                            if isinstance(item, dict):
                                name = item.get('name') or item.get('collectionName')
                            elif hasattr(item, 'name'):
                                name = item.name
                            else:
                                continue
                            
                            if name and name not in seen_names:
                                gift_names.add(name)
                                seen_names.add(name)
                        
                        if len(items) < limit:
                            break
                        
                        offset += limit
                        await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Error fetching gifts from Portals: {e}")
        except Exception as e:
            logger.error(f"Error in _get_portals_gift_names: {e}", exc_info=True)
        
        return gift_names
    
    async def _get_tonnel_gift_names(self) -> Set[str]:
        """Получить названия подарков с Tonnel"""
        gift_names = set()
        
        if not search_tonnel or not settings.TONNEL_AUTH:
            return gift_names
        
        try:
            import requests as req_lib
            try:
                from curl_cffi import requests as curl_requests
                requests_lib = curl_requests
            except ImportError:
                requests_lib = req_lib
            
            seen_names = set()
            page = 1
            max_pages = 50  # Максимум 1500 подарков
            
            for page in range(1, max_pages + 1):
                try:
                    url = "https://gifts2.tonnel.network/api/pageGifts"
                    headers = {
                        "accept": "*/*",
                        "content-type": "application/json",
                        "origin": "https://market.tonnel.network",
                        "referer": "https://market.tonnel.network/",
                        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    }
                    
                    json_data = {
                        "page": page,
                        "limit": 30,
                        "sort": '{"message_post_time":-1,"gift_id":-1}',
                        "filter": '{"price":{"$exists":true},"refunded":{"$ne":true},"buyer":{"$exists":false},"export_at":{"$exists":true},"asset":"TON"}',
                        "ref": 0,
                        "price_range": None,
                        "user_auth": settings.TONNEL_AUTH or "",
                    }
                    
                    if hasattr(requests_lib, 'Session') and hasattr(requests_lib.Session, 'impersonate'):
                        session = requests_lib.Session(impersonate="chrome131")
                        response = session.post(url, headers=headers, json=json_data, timeout=30)
                    else:
                        response = requests_lib.post(url, headers=headers, json=json_data, timeout=30)
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    items = data.get('items') or data.get('data') or []
                    
                    if not items:
                        break
                    
                    for item in items:
                        if isinstance(item, dict):
                            name = item.get('gift_name') or item.get('name') or item.get('collectionName')
                            if name and name not in seen_names:
                                gift_names.add(name)
                                seen_names.add(name)
                    
                    if len(items) < 30:
                        break
                    
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Error fetching gifts from Tonnel at page {page}: {e}")
                    break
        except Exception as e:
            logger.error(f"Error in _get_tonnel_gift_names: {e}", exc_info=True)
        
        return gift_names
    
    async def _get_mrkt_gift_names(self) -> Set[str]:
        """Получить названия подарков с MRKT"""
        gift_names = set()
        if search_mrkt and settings.MRKT_AUTH:
            try:
                items = search_mrkt(limit=100, sort="price_asc", auth_token=settings.MRKT_AUTH)
                if isinstance(items, dict):
                    items = items.get('gifts') or items.get('results') or []
                elif not isinstance(items, list):
                    items = []
                
                seen_ids = set()
                for item in items:
                    if isinstance(item, dict):
                        name = item.get('name') or item.get('collectionName') or item.get('gift_name')
                        item_id = item.get('id') or item.get('giftId') or item.get('giftIdString')
                        if name and item_id and item_id not in seen_ids:
                            gift_names.add(name)
                            seen_ids.add(item_id)
            except Exception as e:
                logger.error(f"Error getting MRKT gift names: {e}")
        return gift_names

    async def _get_getgems_gift_names(self) -> Set[str]:
        """Получить названия подарков (коллекций) с GetGems"""
        gift_names = set()
        if not search_getgems:
            return gift_names
        try:
            api_key = getattr(settings, 'GETGEMS_API_KEY', None) or None
            items = await asyncio.to_thread(
                search_getgems, limit=100, sort="price_asc", api_key=api_key
            )
            if not isinstance(items, list):
                items = []
            seen_ids = set()
            for item in items:
                if isinstance(item, dict):
                    name = item.get('name') or item.get('collectionName') or item.get('collection')
                    item_id = item.get('gift_id') or item.get('address') or item.get('id')
                    if name and (item_id not in seen_ids if item_id else True):
                        gift_names.add(name)
                        if item_id:
                            seen_ids.add(item_id)
        except Exception as e:
            logger.error(f"Error getting GetGems gift names: {e}")
        return gift_names
    
    async def get_models_for_gift(self, gift_name: str, marketplace: Optional[str] = None) -> Set[str]:
        """Получить модели для подарка"""
        # Если gift_name == "ANY", возвращаем пустой набор (модели не нужны)
        if gift_name == "ANY":
            return set()
        
        cache_key = f"models:{gift_name}:{marketplace or 'all'}"
        
        # Проверяем кеш
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return set(cached)
        
        models = set()
        marketplaces = [marketplace] if marketplace else ['portals', 'tonnel', 'mrkt', 'getgems']
        
        for mp in marketplaces:
            try:
                if mp == 'portals' and search:
                    mp_models = await self._get_portals_models(gift_name)
                elif mp == 'tonnel' and search_tonnel:
                    mp_models = await self._get_tonnel_models(gift_name)
                elif mp == 'mrkt' and search_mrkt:
                    mp_models = await self._get_mrkt_models(gift_name)
                elif mp == 'getgems' and search_getgems:
                    mp_models = await self._get_getgems_models(gift_name)
                else:
                    continue
                
                models.update(mp_models)
            except Exception as e:
                logger.error(f"Error getting models from {mp} for {gift_name}: {e}")
        
        # Сохраняем в кеш
        await self.cache.set(cache_key, list(models), ttl=300)
        
        return models
    
    async def _get_portals_models(self, gift_name: str) -> Set[str]:
        """Получить модели с Portals"""
        models = set()
        
        try:
            portals_auth = settings.PORTALS_AUTH if settings.PORTALS_AUTH else self.auth_token
            if not portals_auth:
                if not self.auth_token:
                    if update_auth:
                        if inspect.iscoroutinefunction(update_auth):
                            self.auth_token = await update_auth(settings.API_ID, settings.API_HASH)
                        else:
                            self.auth_token = await asyncio.to_thread(update_auth, settings.API_ID, settings.API_HASH)
                portals_auth = self.auth_token
            
            if portals_auth and search:
                try:
                    if inspect.iscoroutinefunction(search):
                        items = await search(gift_name=gift_name, limit=100, sort="price_asc", authData=portals_auth)
                    else:
                        items = await asyncio.to_thread(search, gift_name=gift_name, limit=100, sort="price_asc", authData=portals_auth)
                    
                    if isinstance(items, dict):
                        items = items.get('results') or items.get('items') or []
                    elif not isinstance(items, list):
                        return models
                    
                    for item in items:
                        if isinstance(item, dict):
                            model = item.get('model') or item.get('modelName') or item.get('model_name')
                        elif hasattr(item, 'model'):
                            model = item.model
                        else:
                            continue
                        
                        if model:
                            models.add(model)
                except Exception as e:
                    logger.error(f"Error getting models from Portals for {gift_name}: {e}")
        except Exception as e:
            logger.error(f"Error in _get_portals_models: {e}")
        
        return models
    
    async def _get_tonnel_models(self, gift_name: str) -> Set[str]:
        """Получить модели с Tonnel"""
        models = set()
        
        if not search_tonnel or not settings.TONNEL_AUTH:
            return models
        
        try:
            items = search_tonnel(gift_name=gift_name, limit=100, sort="price_asc", authData=settings.TONNEL_AUTH)
            if isinstance(items, dict):
                items = items.get('results') or items.get('items') or items.get('gifts') or []
            elif not isinstance(items, list):
                return models
            
            for item in items:
                if isinstance(item, dict):
                    model = item.get('model') or item.get('modelName') or item.get('model_name')
                    if model:
                        models.add(model)
        except Exception as e:
            logger.error(f"Error getting models from Tonnel for {gift_name}: {e}")
        
        return models
    
    async def _get_mrkt_models(self, gift_name: str) -> Set[str]:
        """Получить модели с MRKT"""
        models = set()
        
        if not search_mrkt or not settings.MRKT_AUTH:
            return models
        
        try:
            items = search_mrkt(gift_name=gift_name, limit=100, sort="price_asc", auth_token=settings.MRKT_AUTH)
            if isinstance(items, dict):
                items = items.get('gifts') or items.get('results') or items.get('items') or []
            elif not isinstance(items, list):
                return models
            
            for item in items:
                if isinstance(item, dict):
                    model = item.get('modelName') or item.get('model') or item.get('model_name')
                    if model:
                        models.add(model)
        except Exception as e:
            logger.error(f"Error getting models from MRKT for {gift_name}: {e}")
        
        return models

    async def _get_getgems_models(self, gift_name: str) -> Set[str]:
        """Получить модели с GetGems"""
        models = set()
        if not search_getgems:
            return models
        try:
            api_key = getattr(settings, 'GETGEMS_API_KEY', None) or None
            items = await asyncio.to_thread(
                search_getgems,
                gift_name=gift_name,
                limit=100,
                sort="price_asc",
                api_key=api_key,
            )
            if not isinstance(items, list):
                return models
            for item in items:
                if isinstance(item, dict):
                    model = item.get('model') or item.get('modelName') or item.get('model_name')
                    if model and str(model).strip() and str(model).strip() != 'N/A':
                        models.add(str(model).strip())
        except Exception as e:
            logger.error(f"Error getting models from GetGems for {gift_name}: {e}")
        return models
    
    async def get_all_gift_names(self) -> Set[str]:
        """Получить все уникальные названия подарков со всех маркетплейсов"""
        all_names = set()
        
        for marketplace in ['portals', 'tonnel', 'mrkt', 'getgems']:
            names = await self.get_all_gift_names_from_marketplace(marketplace)
            all_names.update(names)
            await asyncio.sleep(0.05)  # Оптимизированная задержка между маркетплейсами
        
        return all_names

