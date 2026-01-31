## Быстрая проверка исправления ngrok подключения

### Шаг 1: Запустить server.py

```powershell
cd C:\Users\mtvej\Desktop\gg\portals_gifts_bot
python gui/server.py
```

Должно вывести:
```
Starting GUI server on http://localhost:5000
Open http://localhost:5000 in your browser
```

### Шаг 2: Запустить ngrok в другом терминале

```powershell
ngrok http 5000
```

Скопируйте выданный URL (например: `https://abc-def-123-456.ngrok-free.app`)

### Шаг 3: Открыть miniapp с параметром ngrok URL

В браузере откройте:
```
https://YOUR_USERNAME.github.io/portals_gifts_bot/?api=https://abc-def-123-456.ngrok-free.app
```

Замените `YOUR_USERNAME` на ваш логин GitHub и `abc-def-123-456.ngrok-free.app` на реальный URL от ngrok

### Шаг 4: Проверить консоль браузера (F12 → Console)

Вы должны увидеть сообщение:
```
Connected to server
```

### Шаг 5: Проверить работу miniapp

1. Нажмите кнопку "Мониторинг" (Play кнопка)
2. Выберите маркетплейсы (например, "Portals")
3. Нажмите "Включить мониторинг"
4. Должны начать отображаться подарки в реальном времени

### Что было исправлено

В файле `miniapp/app.js` добавлена поддержка заголовка `ngrok-skip-browser-warning` при подключении WebSocket:

- **Было**: простое подключение без заголовков
- **Стало**: подключение с заголовком для ngrok, если URL содержит `ngrok`

Это позволяет WebSocket соединению пройти через ngrok без перехвата "Visit Site" страницы.
