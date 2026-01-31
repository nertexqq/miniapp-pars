# Portals Gifts — Telegram Mini App

Веб-приложение мониторинга подарков Portals, Tonnel, MRKT и GetGems.

## Быстрый запуск

### Локально (для разработки)
```bash
cd miniapp
python server.py
```
Откройте в браузере: `http://localhost:5001`

### Через ngrok (для Telegram Mini App)
```bash
# Если сервер уже запущен
ngrok http 5001

# Используйте URL:
https://nertexqq.github.io/miniapp-pars/?api=https://YOUR_NGROK_URL
```

## Архитектура

- **Фронтенд**: `app.js`, `index.html`, `style.css` (Flask раздаёт статику)
- **Бэкенд**: `server.py` — Flask + Socket.IO для парсинга и реал-тайм обновлений
- **Интеграция маркетплейсов**: Portals, Tonnel, MRKT, GetGems

## API Endpoints

- `GET /api/status` — статус мониторинга
- `GET /api/gifts` — последние подарки (список)
- `GET /api/filters` — текущие фильтры
- `POST /api/filters` — обновить фильтры (маркетплейсы, коллекции, модели, цена)
- `POST /api/toggle` — включить/выключить мониторинг
- `GET /api/suggestions?type=collection` — список коллекций
- `GET /api/suggestions?type=model&collections=Col1,Col2` — модели по коллекциям

## WebSocket события

- `connect` / `disconnect` — подключение клиента
- `new_gift` — новый подарок найден (broadcast)

## Переменные окружения (.env)

```env
PORTALS_AUTH=tma ...
TONNEL_AUTH=user=...
MRKT_AUTH=...
GETGEMS_API_KEY=...
CHECK_INTERVAL=60
FLOOR_CACHE_TTL=300
```

## Деплой GitHub Pages + ngrok

1. GitHub Pages: `https://nertexqq.github.io/miniapp-pars/`
2. Сервер на ngrok: `https://YOUR_NGROK.ngrok-free.app`
3. Откройте: `https://nertexqq.github.io/miniapp-pars/?api=https://YOUR_NGROK.ngrok-free.app`

## Требования

- Python 3.8+
- Flask, Flask-SocketIO, eventlet
- Маркетплейс API (обёртки: portalsmp, tonnelmp_wrapper, mrktmp_wrapper, getgems_wrapper)

- `index.html` — разметка и подключение Telegram Web App SDK.
- `app.js` — логика: API_BASE из `?api=`, тема Telegram, запросы к API.
- `style.css` — стили (копия из `gui/static/`).
