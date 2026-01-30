"""
ORM сущности для базы данных
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    """Модель пользователя"""
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    notifications_enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Gift:
    """Модель подарка"""
    id: Optional[int] = None
    name: str = ""
    model: Optional[str] = None
    price: Optional[float] = None
    floor_price: Optional[float] = None
    model_floor_price: Optional[float] = None
    photo_url: Optional[str] = None
    model_rarity: Optional[str] = None
    user_id: int = 0
    marketplace: str = "portals"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class UserMarketplace:
    """Модель настроек маркетплейса пользователя"""
    user_id: int
    marketplace: str
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class PriceFilter:
    """Модель фильтра цены"""
    user_id: int
    gift_name: str
    model: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Admin:
    """Модель администратора"""
    user_id: int
    created_at: Optional[datetime] = None


