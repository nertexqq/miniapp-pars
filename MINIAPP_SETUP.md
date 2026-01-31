# Запуск Miniapp сервера

## Что было сделано

Создан полноценный **server.py** для папки `miniapp/`, который:

1. ✅ Обслуживает фронтенд (HTML, CSS, JS)
2. ✅ Предоставляет API для парсинга подарков
3. ✅ Интегрирует все маркетплейсы (Portals, Tonnel, MRKT, GetGems)
4. ✅ Работает с WebSocket для реал-тайм обновлений
5. ✅ Поддерживает фильтры (маркетплейсы, коллекции, модели, цена)
6. ✅ Кэшит цены (floor prices)

## Быстрый запуск

### Локально (для разработки)

```bash
# Способ 1: Через батник (Windows)
run_miniapp.bat

# Способ 2: Вручную
cd miniapp
python server.py
```

Откройте в браузере: **http://localhost:5001**

### Через ngrok (для Telegram Mini App или удалённого доступа)

```bash
# В новом терминале
ngrok http 5001

# Получите URL типа: https://abc123.ngrok-free.app

# Откройте в браузере:
# https://abc123.ngrok-free.app
# или через GitHub Pages:
# https://nertexqq.github.io/miniapp-pars/?api=https://abc123.ngrok-free.app
```

## Архитектура

```
miniapp/
├── server.py          ← НОВЫЙ: Flask сервер с парсингом
├── app.js             ← Фронтенд логика
├── index.html         ← HTML приложения
├── style.css          ← Стили
└── README.md          ← Документация
```

## API Endpoints

| Метод | Endpoint | Описание |
|-------|----------|---------|
| GET | `/` | Главная страница |
| GET | `/api/status` | Статус мониторинга |
| GET | `/api/gifts` | Последние подарки (JSON массив) |
| GET | `/api/filters` | Текущие фильтры |
| POST | `/api/filters` | Обновить фильтры |
| POST | `/api/toggle` | Включить/выключить мониторинг |
| GET | `/api/suggestions?type=collection` | Список коллекций |
| GET | `/api/suggestions?type=model&collections=Col1,Col2` | Модели по коллекциям |

## Примеры запросов

### Включить мониторинг с маркетплейсами

```bash
curl -X POST http://localhost:5001/api/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

### Обновить фильтры

```bash
curl -X POST http://localhost:5001/api/filters \
  -H "Content-Type: application/json" \
  -d '{
    "marketplaces": ["portals", "tonnel"],
    "collections": ["Frenzies", "Ponk"],
    "min_price": 1.5,
    "max_price": 10.0
  }'
```

### Получить последние подарки

```bash
curl http://localhost:5001/api/gifts
```

Ответ:
```json
[
  {
    "id": "portals_12345",
    "marketplace": "portals",
    "name": "Frenzies",
    "model": "Santa",
    "price": 2.5,
    "photo_url": "...",
    "gift_number": "42",
    "floor_price": 2.0,
    "model_floor_price": 1.8,
    "marketplace_id": "12345",
    "timestamp": "2025-01-31T10:30:00.000000"
  },
  ...
]
```

## Переменные окружения (.env)

```env
# Telegram API (для Portals/auth)
API_ID=33432004
API_HASH=ceb4716304ce30d4d5570304a2352057

# Маркетплейсы
PORTALS_AUTH=tma query_id=...
TONNEL_AUTH=user=%7B...
MRKT_AUTH=2d43791a-...
GETGEMS_API_KEY=1769816090066-...

# Параметры парсинга
CHECK_INTERVAL=60          # Интервал проверки маркетплейсов (сек)
FLOOR_CACHE_TTL=300        # TTL кэша цен (сек)
TONNEL_FEE_RATE=0.06       # Комиссия Tonnel

# GUI Secret
GUI_SECRET_KEY=portals-gifts-gui-secret-key
```

## WebSocket события (Real-time)

Когда найден новый подарок, сервер отправляет через WebSocket:

```javascript
socket.on('new_gift', (giftData) => {
  console.log('New gift:', giftData);
  // Обновляем UI
});
```

## Отличия от GUI сервера

| Особенность | GUI (gui/server.py) | Mini App (miniapp/server.py) |
|-------------|-------------------|---------------------------|
| Порт | 5000 | 5001 |
| Web UI | Полнофункциональный | Встроенный в miniapp |
| Лимит подарков | 200 в памяти | 200 в памяти |
| Кэш каталога | Сохраняется на диск | В памяти |
| Socket.IO | ✅ | ✅ |
| Размер | ~1.5 KB строк | ~300 KB строк (оптимизирован) |

## Интеграция с GitHub Pages

Если хотите раздавать фронтенд через GitHub Pages, а сервер через ngrok:

```html
<!-- index.html (на GitHub Pages) -->
<script>
  const API_BASE = new URLSearchParams(location.search).get('api') || '';
  // Используйте API_BASE для всех запросов
</script>
```

Откройте: `https://nertexqq.github.io/miniapp-pars/?api=https://YOUR_NGROK.ngrok-free.app`

## Решение проблем

### Ошибка: "Address already in use"
```bash
# Измените порт в server.py (строка ~340):
# socketio.run(app, host='0.0.0.0', port=5002, ...)  # Измените 5001 на 5002
```

### WebSocket не подключается
- Проверьте, что ngrok выбран для WebSocket: `ngrok http 5001 --request-header-add="Authorization: Bearer YOUR_TOKEN"`
- Или используйте флаг: `--web-addr localhost:4040`

### Подарки не появляются
1. Проверьте, что маркетплейсы включены в фильтрах: `POST /api/filters` с `marketplaces: ["portals"]`
2. Проверьте, что мониторинг включен: `POST /api/toggle` с `enabled: true`
3. Посмотрите консоль сервера (py) на ошибки
4. Проверьте переменные окружения в `.env`

## Файлы, созданные/изменённые

- ✅ **miniapp/server.py** - Новый файл (парсинг + API)
- ✅ **miniapp/README.md** - Обновлен
- ✅ **run_miniapp.bat** - Новый батник для быстрого запуска

## Следующие шаги

1. Запустите сервер: `python miniapp/server.py`
2. Откройте браузер: `http://localhost:5001`
3. Проверьте, что фронтенд загружается
4. Включите мониторинг (кнопка в интерфейсе)
5. Выберите маркетплейсы (Portals, Tonnel, MRKT, GetGems)
6. Нажмите "Начать мониторинг"
7. Смотрите подарки в реал-тайме!

## Контакты

При проблемах смотрите логи в терминале сервера. Сервер выводит все ошибки подключения и парсинга.
