# Исправление подключения miniapp к ngrok

## Проблема

При включении miniapp server.py не подключается к ngrok через WebSocket, так что miniapp отображает только HTML каркас без функциональности.

## Причина

Бесплатный ngrok перехватывает браузерные запросы и показывает HTML страницу "Visit Site" вместо того чтобы передать реальный ответ сервера. Это требует специального заголовка `ngrok-skip-browser-warning` для пропуска этого экрана.

### Что было

1. **HTTP fetch запросы** — уже поддерживали заголовок через функцию `apiHeaders()`
2. **WebSocket подключение** — **НЕ** отправляло заголовок `ngrok-skip-browser-warning`

Поэтому при подключении к ngrok через WebSocket соединение не устанавливалось.

## Решение

Добавлен параметр `extraHeaders` при инициализации Socket.IO клиента.

### Измененный код в `miniapp/app.js`

**Было:**
```javascript
const socket = io(API_BASE || window.location.origin, { path: '/socket.io' });
```

**Стало:**
```javascript
const socketOptions = { 
    path: '/socket.io',
    extraHeaders: {}
};
if (API_BASE && API_BASE.includes('ngrok')) {
    socketOptions.extraHeaders['ngrok-skip-browser-warning'] = 'true';
}
const socket = io(API_BASE || window.location.origin, socketOptions);
```

## Как использовать

### Когда miniapp на GitHub Pages, а server.py на локальной машине через ngrok

1. **Запустите server.py:**
```bash
cd c:\Users\mtvej\Desktop\gg\portals_gifts_bot
python gui/server.py
```

2. **В другом терминале запустите ngrok:**
```bash
ngrok http 5000
```

Ngrok выдаст URL вроде: `https://xxx-xx-xxx-xxx.ngrok-free.app`

3. **Откройте miniapp с параметром api:**
```
https://YOUR_USERNAME.github.io/portals_gifts_bot/?api=https://xxx-xx-xxx-xxx.ngrok-free.app
```

Или в боте через BotFather установите Menu Button URL с этим параметром.

4. **Miniapp теперь подключится к server.py через ngrok и будет работать полностью.**

### Когда miniapp и server.py на одном сервере

Просто откройте miniapp без параметра `?api=`, и всё подключится к своему origin.

## Технические детали

- **Заголовок `ngrok-skip-browser-warning`** — стандартный способ обойти ngrok browser warning страницу
- **`extraHeaders`** — параметр Socket.IO для добавления кастомных HTTP заголовков при WebSocket handshake
- **HTTP fetch запросы** — уже поддерживали ngrok благодаря функции `apiHeaders()`
- **server.py** — уже имеет CORS заголовки и поддержку `ngrok-skip-browser-warning` в коде на строке 124

## Проверка

После запуска miniapp:
1. Откройте DevTools (F12) → Console
2. Должна быть строка: `Connected to server`
3. В вкладке Network должны видны WebSocket подключения к `/socket.io`
4. Кнопка "Мониторинг" должна работать, и подарки должны отображаться в реальном времени
