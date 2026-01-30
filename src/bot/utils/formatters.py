"""
Утилиты для форматирования сообщений
"""

import re
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def format_gift_message(
    marketplace: str,
    name: str,
    model: str,
    price: float,
    floor_price: float,
    model_floor: Optional[float],
    gift_floor: Optional[float],
    model_rarity: str,
    gift_number: str,
    model_sales: List[Dict],
    gift_id: str,
    has_inscription: bool = False
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Унифицированное форматирование сообщения о подарке для всех маркетплейсов
    """
    marketplace_names = {
        'portals': 'Portals',
        'tonnel': 'Tonnel',
        'mrkt': 'MRKT'
    }
    marketplace_name = marketplace_names.get(marketplace, marketplace)
    
    # Формируем ссылку на подарок в формате Telegram NFT
    clean_name = re.sub(r'[^\w\s-]', '', str(name)).strip()
    clean_name = re.sub(r'\s+', '', clean_name)  # Убираем все пробелы
    if clean_name and gift_number and gift_number != 'N/A':
        gift_nft_url = f"https://t.me/nft/{clean_name}-{gift_number}"
    else:
        gift_nft_url = ""
    
    # Формируем ссылку на маркетплейс
    marketplace_url = ""
    if marketplace == 'portals' and gift_id and str(gift_id) != 'None':
        marketplace_url = f"https://t.me/portals/market?startapp=gift_{gift_id}"
    elif marketplace == 'tonnel' and gift_id and str(gift_id) != 'None':
        marketplace_url = f"https://t.me/tonnel_network_bot/gift?startapp={gift_id}"
    elif marketplace == 'mrkt' and gift_id and str(gift_id) != 'None':
        # Для MRKT используем хеш
        gift_id_clean = str(gift_id).replace('-', '')
        marketplace_url = f"https://t.me/mrkt/app?startapp={gift_id_clean}"
    
    # Формируем основную строку листинга
    if gift_nft_url:
        listing_line = f"✔️ ЛИСТИНГ\n<a href='{gift_nft_url}'>{name} #{gift_number}</a>"
    else:
        listing_line = f"✔️ ЛИСТИНГ\n{name} #{gift_number}"
    
    if marketplace_url:
        listing_line += f" на <a href='{marketplace_url}'>{marketplace_name}</a>"
    else:
        listing_line += f" на {marketplace_name}"
    
    listing_line += f" за {price:.2f} TON"
    
    # Информация о модели
    model_info = ""
    if model and model != 'N/A':
        model_info = f"Модель: {model}\n"
        if has_inscription:
            model_info += "Подпись: Да\n"
    
    # Флор цены
    floor_info = ""
    if gift_floor is not None:
        floor_info += f"Флор гифта: {gift_floor:.2f} TON\n"
    if model_floor is not None:
        floor_info += f"Флор модели: {model_floor:.2f} TON\n"
    
    # История продаж
    sales_text = ""
    if model_sales:
        sales_lines = []
        for sale in model_sales:
            # Пробуем разные поля для номера подарка
            sale_number = (sale.get('gift_number') or sale.get('external_collection_number') or 
                          sale.get('number') or sale.get('nft_number') or sale.get('id') or 
                          sale.get('gift_id') or sale.get('token_id') or 'N/A')
            
            # Если номер не найден, пробуем извлечь из URL
            if sale_number == 'N/A' or not sale_number:
                sale_url = sale.get('url') or sale.get('nft_url') or sale.get('link') or ''
                if sale_url:
                    # Пробуем извлечь номер из URL вида https://t.me/nft/Name-12345
                    match = re.search(r'-(\d+)(?:/|$)', sale_url)
                    if match:
                        sale_number = match.group(1)
            
            sale_price = sale.get('price') or sale.get('sale_price') or sale.get('amount') or 0
            sale_marketplace = sale.get('marketplace') or 'Tonnel'
            sale_marketplace_name = marketplace_names.get(sale_marketplace, sale_marketplace)
            
            # Форматируем дату
            sale_date = sale.get('date') or sale.get('sold_at') or sale.get('created_at') or sale.get('timestamp')
            days_ago = "N/A"
            if sale_date:
                try:
                    if isinstance(sale_date, (int, float)):
                        if sale_date > 1e10:
                            sale_dt = datetime.fromtimestamp(sale_date / 1000)
                        else:
                            sale_dt = datetime.fromtimestamp(sale_date)
                    elif isinstance(sale_date, str):
                        try:
                            sale_dt = datetime.fromisoformat(sale_date.replace('Z', '+00:00'))
                        except:
                            try:
                                sale_dt = datetime.strptime(sale_date, '%Y-%m-%dT%H:%M:%S')
                            except:
                                sale_dt = datetime.strptime(sale_date, '%Y-%m-%d %H:%M:%S')
                    else:
                        sale_dt = None
                    
                    if sale_dt:
                        now = datetime.now()
                        if sale_dt.tzinfo:
                            now = datetime.now(sale_dt.tzinfo)
                        delta = now - sale_dt
                        
                        total_seconds = int(delta.total_seconds())
                        hours = total_seconds // 3600
                        days = delta.days
                        
                        if days == 0:
                            if hours == 0:
                                minutes = total_seconds // 60
                                if minutes == 0:
                                    days_ago = "только что"
                                elif minutes == 1:
                                    days_ago = "1 минуту назад"
                                elif minutes < 5:
                                    days_ago = f"{minutes} минуты назад"
                                else:
                                    days_ago = f"{minutes} минут назад"
                            elif hours == 1:
                                days_ago = "1 час назад"
                            elif hours < 24:
                                days_ago = f"{hours} часов назад"
                            else:
                                days_ago = "сегодня"
                        elif days == 1:
                            days_ago = "1 день назад"
                        elif days < 7:
                            days_ago = f"{days} дней назад"
                        else:
                            days_ago = sale_dt.strftime("%d.%m.%Y")
                except Exception:
                    pass
            
            # Формируем строку продажи с гиперссылкой
            sale_nft_url = sale.get('url') or sale.get('nft_url') or sale.get('link') or ""
            
            # Если URL нет, создаем его из названия подарка и номера
            if not sale_nft_url and sale_number and sale_number != 'N/A':
                sale_gift_name = sale.get('gift_name') or sale.get('name') or name
                if sale_gift_name:
                    # Очищаем название для URL
                    clean_sale_name = re.sub(r'[^\w\s-]', '', str(sale_gift_name)).strip()
                    clean_sale_name = re.sub(r'\s+', '', clean_sale_name)  # Убираем все пробелы
                    if clean_sale_name:
                        sale_nft_url = f"https://t.me/nft/{clean_sale_name}-{sale_number}"
            
            # Всегда делаем номер гиперссылкой, если есть URL
            if sale_nft_url:
                sale_line = f"<a href='{sale_nft_url}'>#{sale_number}</a>"
            else:
                sale_line = f"#{sale_number}"
            
            # Форматируем цену (убираем лишние знаки после запятой)
            if isinstance(sale_price, (int, float)):
                if sale_price == int(sale_price):
                    sale_price_str = str(int(sale_price))
                else:
                    sale_price_str = f"{sale_price:.2f}".rstrip('0').rstrip('.')
            else:
                sale_price_str = str(sale_price)
            
            sale_line += f" за {sale_price_str} TON на {sale_marketplace_name} - {days_ago}"
            sales_lines.append(sale_line)
        
        if sales_lines:
            sales_text = "\n\n<blockquote>" + "\n".join(sales_lines) + "</blockquote>"
    
    # Формируем полное сообщение
    caption = listing_line
    if model_info:
        caption += "\n" + model_info.strip()
    if floor_info:
        caption += "\n\n" + floor_info.strip()
    if sales_text:
        caption += sales_text
    
    # Кнопка открытия на маркетплейсе
    keyboard = None
    if marketplace_url:
        button_text = f"🔗 Открыть на {marketplace_name}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=button_text, url=marketplace_url)
        ]])
    
    return caption, keyboard

