"""Валидаторы"""

import re
from typing import Optional, Tuple


def validate_price_filter(price_str: str) -> Optional[Tuple[float, float]]:
    """Валидация фильтра цены (формат: "10-30" или "10-30 TON")"""
    # Убираем "TON" и пробелы
    price_str = price_str.replace("TON", "").replace("ton", "").strip()
    
    # Парсим диапазон
    if "-" in price_str:
        parts = price_str.split("-")
        if len(parts) == 2:
            try:
                min_price = float(parts[0].strip())
                max_price = float(parts[1].strip())
                if min_price >= 0 and max_price >= min_price:
                    return (min_price, max_price)
            except ValueError:
                pass
    
    return None


def validate_gift_name(name: str) -> bool:
    """Валидация названия подарка"""
    if not name or len(name.strip()) == 0:
        return False
    if len(name) > 255:
        return False
    return True


