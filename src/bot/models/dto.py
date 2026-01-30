"""
DTO (Data Transfer Objects) для валидации данных
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class GiftDTO(BaseModel):
    """DTO для подарка"""
    name: str
    model: Optional[str] = None
    price: Optional[float] = None
    floor_price: Optional[float] = None
    model_floor_price: Optional[float] = None
    photo_url: Optional[str] = None
    model_rarity: Optional[str] = None
    marketplace: str = "portals"
    gift_id: Optional[str] = None
    gift_number: Optional[str] = None
    has_inscription: bool = False
    
    @validator('marketplace')
    def validate_marketplace(cls, v):
        allowed = ['portals', 'tonnel', 'mrkt', 'getgems']
        if v not in allowed:
            raise ValueError(f"Marketplace must be one of {allowed}")
        return v


class UserDTO(BaseModel):
    """DTO для пользователя"""
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    notifications_enabled: bool = True


class PriceFilterDTO(BaseModel):
    """DTO для фильтра цены"""
    gift_name: str
    model: Optional[str] = None
    min_price: Optional[float] = Field(None, ge=0)
    max_price: Optional[float] = Field(None, ge=0)
    
    @validator('max_price')
    def validate_price_range(cls, v, values):
        if v is not None and 'min_price' in values and values['min_price'] is not None:
            if v < values['min_price']:
                raise ValueError("max_price must be >= min_price")
        return v


class SaleHistoryDTO(BaseModel):
    """DTO для истории продаж"""
    gift_number: str
    price: float
    marketplace: str
    date: datetime
    url: Optional[str] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


