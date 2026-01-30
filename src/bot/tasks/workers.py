"""
Воркеры для фоновых задач
"""

import asyncio
import inspect
import logging
import re
from typing import Dict, List, Set, Optional
from datetime import datetime

from ..di import container
from ..repositories.user_repo import UserRepository
from ..repositories.gift_repo import GiftRepository
from ..repositories.marketplace_repo import MarketplaceRepository
from ..repositories.price_filter_repo import PriceFilterRepository
from ..services.parser import ParserService
from ..utils.formatters import format_gift_message
from ..config import settings

logger = logging.getLogger(__name__)

# Rate limiting для Tonnel API (последнее время запроса)
_tonnel_last_request_time = 0.0
TONNEL_MIN_REQUEST_INTERVAL = 2.0  # Минимальный интервал между запросами к Tonnel (секунды)

# Импорты маркетплейсов
try:
    from aportalsmp import search, update_auth, get_model_floor_price, get_gift_floor_price
except ImportError:
    try:
        from portalsmp import search, update_auth, get_model_floor_price, get_gift_floor_price
    except ImportError:
        search = None
        update_auth = None
        get_model_floor_price = None
        get_gift_floor_price = None

try:
    from tonnelmp_wrapper import (
        search_tonnel, 
        get_tonnel_model_floor_price, 
        get_tonnel_gift_floor_price,
        get_tonnel_model_sales_history
    )
except ImportError:
    search_tonnel = None
    get_tonnel_model_floor_price = None
    get_tonnel_gift_floor_price = None
    get_tonnel_model_sales_history = None

try:
    from mrktmp_wrapper import (
        search_mrkt,
        get_mrkt_model_floor_price,
        get_mrkt_gift_floor_price
    )
except ImportError:
    search_mrkt = None
    get_mrkt_model_floor_price = None
    get_mrkt_gift_floor_price = None

# Глобальные переменные для отслеживания новых подарков
new_gifts_last_ids: Dict[str, Set[str]] = {}
processing_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)
auth_token = None


async def should_process_gift_for_user(user_id: int, gift_name: str, model: str, price: float) -> bool:
    """Проверить, должен ли подарок быть обработан для пользователя"""
    try:
        pool = await container.init_db_pool()
        gift_repo = GiftRepository(pool)
        price_filter_repo = PriceFilterRepository(pool)
        
        # Получаем выбранные подарки пользователя
        try:
            user_gifts = await gift_repo.get_by_user(user_id, page=0, per_page=1000)
        except Exception as e:
            logger.error(f"Error getting user gifts for user {user_id}: {e}", exc_info=True)
            return False
        
        if not user_gifts:
            return False
        
        # Нормализуем название и модель подарка для сравнения
        gift_name_normalized = re.sub(r"\s*\([^)]*\)", "", gift_name).strip().lower()
        model_normalized = re.sub(r"\s*\([^)]*\)", "", model).strip().lower() if model != 'N/A' else 'N/A'
        
        # Проверяем, подходит ли подарок под критерии пользователя
        for user_gift in user_gifts:
            user_gift_name = user_gift.get('name', '')
            user_model = user_gift.get('model') or 'ANY'
            
            # Проверка подарка
            gift_matches = False
            if user_gift_name == "ANY":
                gift_matches = True
            else:
                user_gift_clean = re.sub(r"\s*\([^)]*\)", "", user_gift_name).strip().lower()
                gift_matches = user_gift_clean == gift_name_normalized
            
            # Проверка модели
            model_matches = False
            if user_model == "ANY":
                model_matches = True
            else:
                user_model_clean = re.sub(r"\s*\([^)]*\)", "", user_model).strip().lower()
                model_matches = user_model_clean == model_normalized
            
            # Если подарок и модель совпадают, проверяем фильтр цены
            if gift_matches and model_matches:
                should_process = await price_filter_repo.should_process(user_id, gift_name, model, price)
                if should_process:
                    return True
        
        logger.debug(f"[filter] User {user_id}: Gift {gift_name} ({model}) doesn't match any filters")
        return False
    except Exception as e:
        logger.error(f"Error in should_process_gift_for_user: {e}", exc_info=True)
        return False


async def process_new_gift_monitoring(item: Dict, marketplace: str, users: List[int]):
    """
    Обработка нового подарка для мониторинга
    """
    try:
        pool = await container.init_db_pool()
        gift_repo = GiftRepository(pool)
        price_filter_repo = PriceFilterRepository(pool)
        user_repo = UserRepository(pool)
        
        # Извлекаем данные - для разных маркетплейсов поля могут отличаться
        if marketplace == 'portals':
            name = item.get('name') or item.get('collectionName') or item.get('gift_name') or 'Unknown'
        elif marketplace == 'tonnel':
            name = item.get('gift_name') or item.get('name') or item.get('collectionName') or 'Unknown'
        elif marketplace == 'mrkt':
            # Для MRKT используем поля из преобразованного формата
            name = item.get('name') or item.get('collectionName') or item.get('collection_name') or item.get('gift_name') or 'Unknown'
        else:
            name = item.get('name') or item.get('collectionName') or item.get('gift_name') or 'Unknown'
        
        # Для разных маркетплейсов модель может быть в разных полях
        model = None
        if marketplace == 'portals':
            model = item.get('model') or item.get('modelName') or item.get('model_name')
            if not model and 'attributes' in item and isinstance(item['attributes'], list):
                for attr in item['attributes']:
                    if isinstance(attr, dict) and attr.get('type') == 'model':
                        model = attr.get('value')
                        break
        elif marketplace == 'tonnel':
            model = item.get('model') or item.get('modelName') or item.get('model_name')
        elif marketplace == 'mrkt':
            # Для MRKT используем поля из преобразованного формата
            model = item.get('model') or item.get('modelName') or item.get('model_name') or item.get('modelName')
        
        if not model:
            model = 'N/A'
        
        # Извлекаем цену
        price = None
        if marketplace == 'portals':
            price = item.get('price')
        elif marketplace == 'tonnel':
            price = item.get('price') or item.get('raw_price')
        elif marketplace == 'mrkt':
            # Для MRKT цена уже преобразована в mrktmp_wrapper.py
            price = item.get('price') or item.get('salePrice') or item.get('salePriceWithoutFee') or item.get('tonPrice') or item.get('ton_price')
        
        # Преобразуем цену в float
        if price is not None:
            if isinstance(price, str):
                try:
                    price = float(price)
                except ValueError:
                    price = 0.0
            elif not isinstance(price, (int, float)):
                price = 0.0
        else:
            price = 0.0
        
        # Конвертируем из nanoTON если нужно
        price_ton = price
        if price_ton and price_ton > 1000:
            price_ton = price_ton / 1e9
        
        if not price_ton or price_ton <= 0:
            return
        
        # Фильтруем пользователей по выбранным подаркам и фильтрам цены
        filtered_users = []
        for user_id in users:
            if await should_process_gift_for_user(user_id, name, model, price_ton):
                filtered_users.append(user_id)
        
        if not filtered_users:
            return
        
        # Извлекаем ID подарка
        gift_id = None
        if marketplace == 'portals':
            gift_id = (item.get('id') or item.get('gift_id') or item.get('nft_id') or 
                      item.get('giftId') or item.get('_id'))
            if gift_id:
                gift_id = str(gift_id)
        elif marketplace == 'tonnel':
            gift_id = item.get('gift_id') or item.get('id')
            if gift_id:
                gift_id = str(gift_id)
        elif marketplace == 'mrkt':
            # Для MRKT используем mrkt_hash (32 символа hex) для ссылки, или id как fallback
            gift_id = item.get('mrkt_hash') or item.get('id') or item.get('giftId') or item.get('giftIdString') or item.get('hash')
            if gift_id:
                gift_id = str(gift_id).replace('-', '')  # Убираем дефисы для MRKT
                # Проверяем, что это валидный хеш (32 символа hex)
                if len(gift_id) != 32 or not all(c in '0123456789abcdefABCDEF' for c in gift_id):
                    # Если не хеш, пробуем найти хеш в других полях
                    if not item.get('mrkt_hash'):
                        logger.warning(f"[monitor] MRKT gift_id '{gift_id}' is not a valid hash, trying to find hash in other fields")
                        gift_id = None
        
        gift_number = item.get('external_collection_number') or item.get('number') or item.get('giftNumber') or 'N/A'
        
        # Получаем редкость модели
        model_rarity = item.get('model_rarity') or item.get('rarity') or 'N/A'
        if not model_rarity and 'attributes' in item and isinstance(item['attributes'], list):
            for attr in item['attributes']:
                if isinstance(attr, dict) and attr.get('type') == 'model':
                    rarity_per_mille = attr.get('rarity_per_mille')
                    if rarity_per_mille is not None:
                        model_rarity = f"{rarity_per_mille}%"
                    break
        
        # Очищаем название для поиска
        name_clean_for_search = re.sub(r"\s*\([^)]*\)", "", name).strip()
        model_clean = re.sub(r"\s*\([^)]*\)", "", model).strip()
        
        # Получаем флоры и историю продаж параллельно для ускорения
        model_floor = None
        gift_floor = None
        model_sales = []
        
        # Создаем задачи для параллельного выполнения
        tasks = []
        
        # Флор модели
        if marketplace == 'portals' and get_model_floor_price:
            global auth_token
            portals_auth = settings.PORTALS_AUTH or auth_token
            if not portals_auth and update_auth:
                auth_token = await update_auth(settings.API_ID, settings.API_HASH)
                portals_auth = auth_token
            if portals_auth:
                if inspect.iscoroutinefunction(get_model_floor_price):
                    tasks.append(('model_floor', get_model_floor_price(name_clean_for_search, model_clean, portals_auth)))
                else:
                    tasks.append(('model_floor', asyncio.to_thread(get_model_floor_price, name_clean_for_search, model_clean, portals_auth)))
        elif marketplace == 'tonnel' and get_tonnel_model_floor_price and settings.TONNEL_AUTH:
            tasks.append(('model_floor', asyncio.to_thread(get_tonnel_model_floor_price, name_clean_for_search, model_clean, settings.TONNEL_AUTH)))
        elif marketplace == 'mrkt' and get_mrkt_model_floor_price and settings.MRKT_AUTH:
            tasks.append(('model_floor', asyncio.to_thread(get_mrkt_model_floor_price, name_clean_for_search, model_clean, settings.MRKT_AUTH)))
        
        # Флор подарка
        if marketplace == 'portals' and get_gift_floor_price:
            portals_auth = settings.PORTALS_AUTH or auth_token
            if portals_auth:
                if inspect.iscoroutinefunction(get_gift_floor_price):
                    tasks.append(('gift_floor', get_gift_floor_price(name_clean_for_search, portals_auth)))
                else:
                    tasks.append(('gift_floor', asyncio.to_thread(get_gift_floor_price, name_clean_for_search, portals_auth)))
        elif marketplace == 'tonnel' and get_tonnel_gift_floor_price and settings.TONNEL_AUTH:
            tasks.append(('gift_floor', asyncio.to_thread(get_tonnel_gift_floor_price, name_clean_for_search, settings.TONNEL_AUTH)))
        elif marketplace == 'mrkt' and get_mrkt_gift_floor_price and settings.MRKT_AUTH:
            tasks.append(('gift_floor', asyncio.to_thread(get_mrkt_gift_floor_price, name_clean_for_search, settings.MRKT_AUTH)))
        
        # История продаж (только если модель не N/A) - запускаем отдельно с большим таймаутом
        model_sales_task = None
        if get_tonnel_model_sales_history and settings.TONNEL_AUTH and model_clean and model_clean != 'N/A':
            model_sales_task = asyncio.to_thread(get_tonnel_model_sales_history, name_clean_for_search, model_clean, settings.TONNEL_AUTH, 5)
        
        # Выполняем все задачи параллельно с таймаутом для ускорения
        if tasks:
            try:
                # Устанавливаем таймаут 3 секунды для флоров (увеличили для надежности)
                results = await asyncio.wait_for(
                    asyncio.gather(*[task[1] for task in tasks], return_exceptions=True),
                    timeout=3.0
                )
                for i, (task_name, _) in enumerate(tasks):
                    result = results[i]
                    if not isinstance(result, Exception):
                        if task_name == 'model_floor':
                            model_floor = result
                        elif task_name == 'gift_floor':
                            gift_floor = result
            except asyncio.TimeoutError:
                # Если таймаут - продолжаем без флоров
                logger.warning(f"[monitor] Timeout getting floors for {name} ({model}) from {marketplace}")
            except Exception as e:
                logger.error(f"[monitor] Error getting floors for {name} ({model}) from {marketplace}: {e}")
        
        # История продаж запускаем отдельно с большим таймаутом
        if model_sales_task:
            try:
                model_sales = await asyncio.wait_for(model_sales_task, timeout=5.0)
                if not isinstance(model_sales, list):
                    model_sales = []
            except asyncio.TimeoutError:
                logger.warning(f"[monitor] Timeout getting sales history for {name} ({model})")
                model_sales = []
            except Exception as e:
                logger.error(f"[monitor] Error getting sales history for {name} ({model}): {e}")
                model_sales = []
        
        # Проверяем, у кого парсинг всё ещё включён (мог выключиться после старта задачи)
        try:
            enabled_rows = await user_repo.get_users_with_monitoring_enabled()
            enabled_ids = {r['user_id'] for r in enabled_rows}
            filtered_users = [u for u in filtered_users if u in enabled_ids]
        except Exception as e:
            logger.warning(f"[monitor] Failed to re-check parsing enabled: {e}")
        
        if not filtered_users:
            return
        
        # Форматируем сообщение
        caption, keyboard = format_gift_message(
            marketplace=marketplace,
            name=name,
            model=model,
            price=price_ton,
            floor_price=price_ton,
            model_floor=model_floor,
            gift_floor=gift_floor,
            model_rarity=model_rarity,
            gift_number=str(gift_number),
            model_sales=model_sales,
            gift_id=str(gift_id) if gift_id else 'N/A',
            has_inscription=False
        )
        
        # Отправляем уведомления пользователям
        bot = await container.init_bot()
        photo_url = item.get('photo_url') or item.get('image_url') or item.get('image')
        
        for user_id in filtered_users:
            try:
                if photo_url:
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=photo_url,
                        caption=caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    await bot.send_message(
                        chat_id=user_id,
                        text=caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error in process_new_gift_monitoring: {e}", exc_info=True)


async def process_new_gift_monitoring_with_semaphore(item: Dict, marketplace: str, users: List[int]):
    """Обертка для обработки подарка - запускаем сразу без семафора для максимальной скорости"""
    # Запускаем обработку сразу без ожидания семафора
    await process_new_gift_monitoring(item, marketplace, users)


async def check_new_gifts():
    """
    Проверка новых подарков на всех маркетплейсах
    """
    try:
        pool = await container.init_db_pool()
        user_repo = UserRepository(pool)
        marketplace_repo = MarketplaceRepository(pool)
        
        # Получаем пользователей с включенным мониторингом
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT user_id FROM new_gifts_monitoring WHERE enabled = TRUE")
                results = await cur.fetchall()
                users_to_notify = [row[0] for row in results]
        
        if not users_to_notify:
            return
        
        # Инициализируем множества для отслеживания ID
        for mp in ['portals', 'tonnel', 'mrkt']:
            if mp not in new_gifts_last_ids:
                new_gifts_last_ids[mp] = set()
        
        # Получаем маркетплейсы для проверки
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT DISTINCT um.marketplace 
                    FROM user_marketplaces um
                    INNER JOIN new_gifts_monitoring ngm ON um.user_id = ngm.user_id
                    WHERE um.enabled = TRUE AND ngm.enabled = TRUE
                """)
                results = await cur.fetchall()
                marketplaces_to_check = {row[0] for row in results if row[0] in ['portals', 'tonnel', 'mrkt']}
                
                # Если нет настроек маркетплейсов, включаем все по умолчанию
                await cur.execute("""
                    SELECT DISTINCT user_id FROM user_marketplaces
                """)
                users_with_marketplace_settings = {row[0] for row in await cur.fetchall()}
                
                # Если у пользователя нет настроек, добавляем все маркетплейсы
                for user_id in users_to_notify:
                    if user_id not in users_with_marketplace_settings:
                        logger.info(f"[monitor] User {user_id} has no marketplace settings, enabling all by default")
                        marketplaces_to_check.update(['portals', 'tonnel', 'mrkt'])
                        break  # Достаточно одного пользователя без настроек
                
                # Если marketplaces_to_check пусто, значит у всех пользователей есть настройки, но все маркетплейсы выключены
                # В этом случае тоже включаем все по умолчанию
                if not marketplaces_to_check:
                    logger.info("[monitor] No enabled marketplaces found, enabling all by default")
                    marketplaces_to_check = {'portals', 'tonnel', 'mrkt'}
        
        logger.info(f"[monitor] Marketplaces to check: {marketplaces_to_check}, MRKT_AUTH: {'SET' if settings.MRKT_AUTH else 'NOT SET'}")
        
        if not marketplaces_to_check:
            logger.debug("[monitor] No marketplaces to check")
            return
        
        # Получаем настройки маркетплейсов для всех пользователей заранее
        marketplace_users_cache = {}
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for mp in marketplaces_to_check:
                    placeholders = ','.join(['%s'] * len(users_to_notify))
                    await cur.execute(f"""
                        SELECT user_id FROM user_marketplaces 
                        WHERE user_id IN ({placeholders}) AND marketplace = %s AND enabled = TRUE
                    """, users_to_notify + [mp])
                    results = await cur.fetchall()
                    marketplace_users_cache[mp] = {row[0] for row in results}
                    
                    # Добавляем пользователей без настроек (по умолчанию включены все)
                    await cur.execute(f"""
                        SELECT DISTINCT user_id FROM user_marketplaces WHERE user_id IN ({placeholders})
                    """, users_to_notify)
                    users_with_settings = {row[0] for row in await cur.fetchall()}
                    for user_id in users_to_notify:
                        if user_id not in users_with_settings:
                            marketplace_users_cache[mp].add(user_id)
        
        # Обрабатываем каждый маркетплейс
        async def process_marketplace(marketplace: str):
            """Обработка одного маркетплейса"""
            try:
                logger.info(f"[monitor] process_marketplace called for: {marketplace}")
                if marketplace not in ['portals', 'tonnel', 'mrkt']:
                    logger.warning(f"[monitor] Unknown marketplace: {marketplace}")
                    return
                
                items = []
                if marketplace == 'portals' and search:
                    global auth_token
                    portals_auth = settings.PORTALS_AUTH or auth_token
                    if not portals_auth:
                        if update_auth:
                            auth_token = await update_auth(settings.API_ID, settings.API_HASH)
                            portals_auth = auth_token
                    
                    if portals_auth:
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                if inspect.iscoroutinefunction(search):
                                    items = await search(limit=999, sort="latest", authData=portals_auth)
                                else:
                                    items = await asyncio.to_thread(search, limit=999, sort="latest", authData=portals_auth)
                                
                                if isinstance(items, str):
                                    if "429" in items and attempt < max_retries - 1:
                                        await asyncio.sleep(0.5)  # Минимальная задержка при rate limit
                                        continue
                                    logger.error(f"Portals search returned error: {items}")
                                    break
                                
                                if isinstance(items, dict):
                                    items = items.get('results') or items.get('items') or []
                                elif not isinstance(items, list):
                                    if hasattr(items, '__iter__'):
                                        items = list(items)
                                    else:
                                        break
                                
                                # Конвертируем объекты в словари
                                if items and not isinstance(items[0], dict):
                                    converted = []
                                    for item in items:
                                        if isinstance(item, dict):
                                            converted.append(item)
                                        elif hasattr(item, '__dict__'):
                                            converted.append(item.__dict__)
                                        elif hasattr(item, 'id'):
                                            item_dict = {}
                                            for attr in ['id', 'name', 'model', 'price', 'floor_price', 
                                                        'external_collection_number', 'model_rarity', 'photo_url']:
                                                if hasattr(item, attr):
                                                    item_dict[attr] = getattr(item, attr)
                                            if item_dict:
                                                converted.append(item_dict)
                                    if converted:
                                        items = converted
                                
                                break
                            except Exception as e:
                                if "429" in str(e) and attempt < max_retries - 1:
                                    await asyncio.sleep(0.5)  # Минимальная задержка при rate limit
                                    continue
                                logger.error(f"Error fetching Portals items: {e}")
                                items = []
                                break
                
                elif marketplace == 'tonnel' and search_tonnel and settings.TONNEL_AUTH:
                    try:
                        # Rate limiting: ждем минимум 2 секунды между запросами к Tonnel
                        global _tonnel_last_request_time
                        import time
                        current_time = time.time()
                        time_since_last = current_time - _tonnel_last_request_time
                        if time_since_last < TONNEL_MIN_REQUEST_INTERVAL:
                            wait_time = TONNEL_MIN_REQUEST_INTERVAL - time_since_last
                            logger.debug(f"[monitor] Rate limiting Tonnel: waiting {wait_time:.2f}s")
                            await asyncio.sleep(wait_time)
                        _tonnel_last_request_time = time.time()
                        
                        logger.debug(f"[monitor] Fetching Tonnel items...")
                        # Проверяем, асинхронная ли функция
                        if inspect.iscoroutinefunction(search_tonnel):
                            items = await search_tonnel(limit=999, sort="latest", authData=settings.TONNEL_AUTH)
                        else:
                            items = await asyncio.to_thread(search_tonnel, limit=999, sort="latest", authData=settings.TONNEL_AUTH)
                        
                        logger.debug(f"[monitor] Tonnel returned: type={type(items)}, is_list={isinstance(items, list)}")
                        
                        if isinstance(items, dict):
                            items = items.get('results') or items.get('items') or items.get('gifts') or []
                            logger.debug(f"[monitor] Tonnel items from dict: {len(items) if isinstance(items, list) else 0}")
                        elif isinstance(items, str):
                            logger.error(f"Tonnel returned error: {items}")
                            items = []
                        elif not isinstance(items, list):
                            logger.warning(f"Tonnel returned unexpected type: {type(items)}, converting...")
                            if hasattr(items, '__iter__'):
                                items = list(items)
                            else:
                                items = []
                    except Exception as e:
                        logger.error(f"Error fetching Tonnel items: {e}", exc_info=True)
                        items = []
                
                elif marketplace == 'mrkt':
                    logger.info(f"[monitor] MRKT: Processing started, search_mrkt={search_mrkt is not None}, MRKT_AUTH={'SET' if settings.MRKT_AUTH else 'NOT SET'}")
                    if not search_mrkt:
                        logger.warning("[monitor] MRKT: search_mrkt function not available")
                        items = []
                    elif not settings.MRKT_AUTH:
                        logger.warning("[monitor] MRKT: MRKT_AUTH not set in settings")
                        items = []
                    else:
                        try:
                            logger.info(f"[monitor] MRKT: Fetching items with auth token: {settings.MRKT_AUTH[:20]}...")
                            # Проверяем, асинхронная ли функция
                            # Для MRKT максимум 20 подарков за запрос, используем latest для новых
                            if inspect.iscoroutinefunction(search_mrkt):
                                items = await search_mrkt(limit=20, sort="latest", auth_token=settings.MRKT_AUTH)
                            else:
                                items = await asyncio.to_thread(search_mrkt, limit=20, sort="latest", auth_token=settings.MRKT_AUTH)
                            
                            logger.info(f"[monitor] MRKT returned: type={type(items)}, is_list={isinstance(items, list)}, is_str={isinstance(items, str)}")
                            
                            if isinstance(items, str):
                                logger.error(f"MRKT returned error string: {items}")
                                items = []
                            elif isinstance(items, dict):
                                items = items.get('gifts') or items.get('results') or items.get('items') or []
                                logger.info(f"[monitor] MRKT items from dict: {len(items) if isinstance(items, list) else 0}")
                                if isinstance(items, list) and items:
                                    logger.info(f"[monitor] MRKT first item keys: {list(items[0].keys())[:20] if isinstance(items[0], dict) else 'N/A'}")
                            elif isinstance(items, list):
                                logger.info(f"[monitor] MRKT returned list with {len(items)} items")
                                if items and isinstance(items[0], dict):
                                    logger.info(f"[monitor] MRKT first item keys: {list(items[0].keys())[:20]}")
                            else:
                                logger.warning(f"MRKT returned unexpected type: {type(items)}, value: {str(items)[:200]}")
                                if hasattr(items, '__iter__') and not isinstance(items, (str, bytes)):
                                    try:
                                        items = list(items)
                                        logger.info(f"[monitor] MRKT converted to list: {len(items)} items")
                                    except Exception as e:
                                        logger.error(f"MRKT failed to convert to list: {e}")
                                        items = []
                                else:
                                    items = []
                        except Exception as e:
                            logger.error(f"Error fetching MRKT items: {e}", exc_info=True)
                            items = []
                
                if not isinstance(items, list) or not items:
                    logger.debug(f"[monitor] {marketplace}: No items to process (type: {type(items)}, count: {len(items) if isinstance(items, list) else 'N/A'})")
                    return
                
                logger.info(f"[monitor] {marketplace}: Got {len(items)} items to process")
                
                # Обрабатываем новые подарки
                new_count = 0
                for item in items:
                    item_dict = None
                    if isinstance(item, dict):
                        item_dict = item
                    elif hasattr(item, '__dict__'):
                        item_dict = item.__dict__
                    elif hasattr(item, 'id'):
                        item_dict = {}
                        for attr in ['id', 'gift_id', 'nft_id', 'name', 'collectionName', 'gift_name',
                                    'model', 'modelName', 'price', 'floor_price', 'photo_url',
                                    'external_collection_number', 'number', 'model_rarity']:
                            if hasattr(item, attr):
                                item_dict[attr] = getattr(item, attr)
                    
                    if not item_dict:
                        continue
                    
                    # Получаем ID подарка
                    gift_id = None
                    if marketplace == 'portals':
                        gift_id = (item_dict.get('id') or item_dict.get('gift_id') or 
                                  item_dict.get('nft_id') or item_dict.get('giftId'))
                        if gift_id:
                            gift_id = str(gift_id)
                    elif marketplace == 'tonnel':
                        # Для Tonnel пробуем разные поля
                        gift_id = (item_dict.get('gift_id') or item_dict.get('id') or 
                                  item_dict.get('token_id') or item_dict.get('nft_id'))
                        if gift_id:
                            gift_id = str(gift_id)
                    elif marketplace == 'mrkt':
                        # Для MRKT пробуем разные поля
                        gift_id = (item_dict.get('id') or item_dict.get('mrkt_hash') or 
                                  item_dict.get('giftId') or item_dict.get('hash') or 
                                  item_dict.get('token_id') or item_dict.get('uuid'))
                        if gift_id:
                            gift_id = str(gift_id).replace('-', '')  # Убираем дефисы для MRKT
                    
                    if not gift_id:
                        logger.debug(f"[monitor] {marketplace}: Skipping item - no ID found, keys: {list(item_dict.keys())[:10]}")
                        continue
                    
                    gift_id_str = f"{marketplace}_{gift_id}"
                    
                    # Проверяем, новый ли это подарок
                    if gift_id_str not in new_gifts_last_ids[marketplace]:
                        new_gifts_last_ids[marketplace].add(gift_id_str)
                        new_count += 1
                        
                        logger.debug(f"[monitor] {marketplace}: New gift found - ID: {gift_id}, name: {item_dict.get('name') or item_dict.get('gift_name') or item_dict.get('collectionName')}")
                        
                        # Используем кэш для фильтрации пользователей
                        filtered_users = list(marketplace_users_cache.get(marketplace, set()))
                        
                        if filtered_users:
                            logger.debug(f"[monitor] {marketplace}: Processing gift for {len(filtered_users)} users")
                            asyncio.create_task(process_new_gift_monitoring_with_semaphore(item_dict, marketplace, filtered_users))
                        else:
                            logger.debug(f"[monitor] {marketplace}: No users to notify for this gift")
                        
                        # Ограничиваем размер множества
                        if len(new_gifts_last_ids[marketplace]) > 1000:
                            new_gifts_last_ids[marketplace] = set(list(new_gifts_last_ids[marketplace])[-1000:])
                
            except Exception as e:
                logger.error(f"[monitor] Error checking {marketplace}: {e}", exc_info=True)
        
        # Запускаем обработку всех маркетплейсов параллельно
        logger.info(f"[monitor] Starting processing for {len(marketplaces_to_check)} marketplaces: {sorted(marketplaces_to_check)}")
        tasks = [process_marketplace(mp) for mp in sorted(marketplaces_to_check)]
        if tasks:
            logger.info(f"[monitor] Created {len(tasks)} tasks, executing...")
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(f"[monitor] All marketplace tasks completed")
        else:
            logger.warning("[monitor] No tasks to process - no marketplaces to check")
    
    except Exception as e:
        logger.error(f"Error in check_new_gifts: {e}", exc_info=True)


async def check_prices():
    """
    Проверка изменения цен на отслеживаемые подарки
    """
    # TODO: Реализовать проверку цен
    logger.debug("Price check not implemented yet")
