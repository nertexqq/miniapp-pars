"""
Обертка для GetGems Marketplace API (подарки на продаже)
Эндпоинт: https://api.getgems.io/public-api/v1/nfts/offchain/on-sale/gifts
Авторизация: Authorization: Bearer <API_KEY>
"""

import logging
import os
from typing import List, Dict, Optional
import requests

logger = logging.getLogger(__name__)

GETGEMS_BASE_URL = 'https://api.getgems.io/public-api'
GETGEMS_GIFTS_URL = f'{GETGEMS_BASE_URL}/v1/nfts/offchain/on-sale/gifts'
GETGEMS_GIFTS_HISTORY_URL = f'{GETGEMS_BASE_URL}/v1/nfts/history/gifts'
GETGEMS_NFT_URL_TEMPLATE = f'{GETGEMS_BASE_URL}/v1/nft/{{nftAddress}}'
GETGEMS_API_KEY = None


def _headers(api_key: Optional[str] = None) -> Dict[str, str]:
    key = api_key or os.getenv('GETGEMS_API_KEY') or GETGEMS_API_KEY
    if not key:
        raise ValueError('GetGems API key is missing (set GETGEMS_API_KEY env var or pass api_key=)')
    return {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    }


def _fetch_on_sale_items(fetch_limit: int, api_key: Optional[str]) -> List[Dict]:
    resp = requests.get(
        GETGEMS_GIFTS_URL,
        headers=_headers(api_key),
        params={'limit': fetch_limit},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        logger.warning('GetGems API success=false')
        return []
    r = data.get('response') or {}
    raw_items = r.get('items') or []
    return [it for it in raw_items if isinstance(it, dict)]


def _fetch_nft_details(nft_address: str, api_key: Optional[str]) -> Optional[Dict]:
    if not nft_address:
        return None
    url = GETGEMS_NFT_URL_TEMPLATE.format(nftAddress=nft_address)
    resp = requests.get(
        url,
        headers=_headers(api_key),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        return None
    r = data.get('response')
    return r if isinstance(r, dict) else None


def _fetch_history_items(fetch_limit: int, types: str, api_key: Optional[str]) -> List[Dict]:
    resp = requests.get(
        GETGEMS_GIFTS_HISTORY_URL,
        headers=_headers(api_key),
        params={'limit': fetch_limit, 'types': types},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        logger.warning('GetGems API success=false')
        return []
    r = data.get('response') or {}
    raw_items = r.get('items') or []
    return [it for it in raw_items if isinstance(it, dict)]


def _parse_gift_item(item: Dict) -> Dict:
    """
    Парсит item из /v1/nfts/offchain/on-sale/gifts в унифицированный формат.
    name: "Whip Cupcake #97737" -> collection "Whip Cupcake", gift_number "97737"
    attributes: [{ traitType: "Model", value: "Heaven Seven" }, ...]
    sale.fullPrice: nanoTON string
    """
    name_raw = item.get('name') or 'Unknown'
    if ' #' in name_raw:
        collection_name, _, num_part = name_raw.rpartition(' #')
        gift_number = num_part.strip() or 'N/A'
    else:
        collection_name = name_raw
        gift_number = 'N/A'

    attrs = item.get('attributes') or []
    attr_map = {a.get('traitType', ''): a.get('value') for a in attrs if isinstance(a, dict)}
    model_name = attr_map.get('Model') or attr_map.get('model') or 'N/A'
    backdrop = attr_map.get('Backdrop') or attr_map.get('backdrop')

    sale = item.get('sale') or {}
    price_raw = sale.get('fullPrice') or sale.get('price')
    price = None
    if price_raw is not None:
        try:
            price = float(price_raw)
            if price > 1e9:
                price = price / 1e9
        except (TypeError, ValueError):
            pass

    photo_url = item.get('image')
    if not photo_url and isinstance(item.get('imageSizes'), dict):
        photo_url = item['imageSizes'].get('352') or item['imageSizes'].get('96')

    return {
        'name': collection_name or 'Unknown',
        'model': str(model_name) if model_name else 'N/A',
        'backdrop': str(backdrop) if backdrop else None,
        'price': round(price, 4) if price is not None else None,
        'gift_number': str(gift_number),
        'gift_id': item.get('address'),
        'photo_url': photo_url,
        'floor_price': None,
        'model_rarity': None,
        'collection_address': item.get('collectionAddress'),
        'attributes': attrs,
    }


def _parse_history_item(event: Dict) -> Optional[Dict]:
    if not isinstance(event, dict):
        return None
    name_raw = event.get('name') or 'Unknown'
    if ' #' in name_raw:
        collection_name, _, num_part = name_raw.rpartition(' #')
        gift_number = num_part.strip() or 'N/A'
    else:
        collection_name = name_raw
        gift_number = 'N/A'

    type_data = event.get('typeData') or {}
    price = None
    price_raw = type_data.get('priceNano') or type_data.get('price')
    if price_raw is not None:
        try:
            price_val = float(price_raw)
            if price_val > 1e9:
                price_val = price_val / 1e9
            price = round(price_val, 4)
        except (TypeError, ValueError):
            price = None

    return {
        'name': collection_name or 'Unknown',
        'model': 'N/A',
        'backdrop': None,
        'price': price,
        'gift_number': str(gift_number),
        'gift_id': event.get('address'),
        'photo_url': None,
        'floor_price': None,
        'model_rarity': None,
        'collection_address': event.get('collectionAddress'),
        'attributes': [],
    }


def search_getgems(
    gift_name: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 20,
    sort: str = "price_asc",
    api_key: Optional[str] = None,
) -> List[Dict]:
    """
    Поиск подарков на продаже на GetGems.
    Эндпоинт возвращает все gifts on sale; фильтрация по коллекции/модели — на нашей стороне.

    Args:
        gift_name: название коллекции (фильтр)
        model: название модели (фильтр)
        limit: макс. количество результатов
        sort: price_asc, price_desc, latest (сортировка по цене — на нашей стороне)
        api_key: API ключ GetGems

    Returns:
        Список словарей в унифицированном формате.
    """
    key = api_key or os.getenv('GETGEMS_API_KEY') or GETGEMS_API_KEY
    if not key:
        logger.warning('GetGems: API key is missing (set GETGEMS_API_KEY env var)')
        return []
    items_out: List[Dict] = []
    fetch_limit = min(max(limit, 1), 100)

    try:
        if sort == 'latest':
            # Get newest listings via history, then enrich with on-sale items to get attributes/images.
            history_items = _fetch_history_items(fetch_limit=fetch_limit, types='putUpForSale', api_key=key)
            history_addresses: List[str] = []
            history_parsed_by_address: Dict[str, Dict] = {}

            for it in history_items:
                parsed = _parse_history_item(it)
                if not parsed:
                    continue
                addr = parsed.get('gift_id')
                if not addr:
                    continue
                if addr not in history_parsed_by_address:
                    history_addresses.append(addr)
                    history_parsed_by_address[addr] = parsed

            for addr in history_addresses:
                raw = None
                try:
                    raw = _fetch_nft_details(addr, api_key=key)
                except Exception as e:
                    logger.warning(f'GetGems: failed to fetch nft details {addr}: {e}')

                # Если детали не удалось получить, хотя бы вернем базовую инфу из history
                parsed = _parse_gift_item(raw) if raw else history_parsed_by_address.get(addr)
                if not parsed:
                    continue
                if gift_name and (gift_name.lower() not in (parsed.get('name') or '').lower()):
                    continue
                if model and (model.lower() not in (parsed.get('model') or '').lower()):
                    continue
                items_out.append(parsed)
                if len(items_out) >= limit:
                    break
        else:
            raw_items = _fetch_on_sale_items(fetch_limit=fetch_limit, api_key=key)

            for it in raw_items:
                parsed = _parse_gift_item(it)
                if not parsed:
                    continue
                if gift_name and (gift_name.lower() not in (parsed.get('name') or '').lower()):
                    continue
                if model and (model.lower() not in (parsed.get('model') or '').lower()):
                    continue
                items_out.append(parsed)
                if len(items_out) >= limit:
                    break

        if sort != 'latest':
            # Сортировка по цене на нашей стороне
            def _price(x: Dict) -> float:
                p = x.get('price')
                return float(p) if p is not None else float('inf')

            if sort == 'price_desc':
                items_out.sort(key=_price, reverse=True)
            else:
                items_out.sort(key=_price)

            items_out = items_out[:limit]
        logger.info(f'GetGems: fetched {len(items_out)} gifts on sale')
        return items_out

    except requests.HTTPError as e:
        logger.error(f'GetGems HTTP error: {e}')
        return []
    except ValueError as e:
        # Missing key or other validation errors — do not spam traceback
        logger.warning(f'GetGems: {e}')
        return []
    except Exception as e:
        logger.error(f'GetGems search error: {e}', exc_info=True)
        return []


def get_getgems_gift_floor_price(gift_name: str, api_key: Optional[str] = None) -> Optional[float]:
    """Флор коллекции (минимальная цена среди на продаже)."""
    try:
        items = search_getgems(gift_name=gift_name, limit=1, sort='price_asc', api_key=api_key)
        if items and items[0].get('price') is not None:
            return float(items[0]['price'])
        return None
    except Exception as e:
        logger.error(f'GetGems gift floor price error: {e}')
        return None


def get_getgems_model_floor_price(gift_name: str, model: str, api_key: Optional[str] = None) -> Optional[float]:
    """Флор модели (минимальная цена среди на продаже)."""
    try:
        items = search_getgems(gift_name=gift_name, model=model, limit=1, sort='price_asc', api_key=api_key)
        if items and items[0].get('price') is not None:
            return float(items[0]['price'])
        return None
    except Exception as e:
        logger.error(f'GetGems model floor price error: {e}')
        return None


def get_getgems_gift_history(gift_address: str, limit: int = 5, api_key: Optional[str] = None) -> List[Dict]:
    """История по подарку — через API не реализовано, заглушка."""
    return []


def get_getgems_model_sales_history(
    gift_name: str, model: str, limit: int = 5, api_key: Optional[str] = None
) -> List[Dict]:
    """История продаж модели — заглушка."""
    return []


def get_getgems_gift_by_id(gift_id: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """
    Получить подарок по address.
    Эндпоинт on-sale/gifts отдает только лоты на продаже; по одному item отдельного
    API может не быть. Ищем в search и возвращаем совпадение по address, иначе None.
    """
    try:
        items = search_getgems(limit=200, api_key=api_key)
        for it in items:
            if it.get('gift_id') == gift_id:
                return it
        return None
    except Exception as e:
        logger.error(f'GetGems gift by id error: {e}')
        return None
