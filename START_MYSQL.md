# Как запустить MySQL на Windows

## Способ 1: Через командную строку (от администратора)

1. Откройте **PowerShell** или **CMD** от имени администратора:
   - Нажмите `Win + X`
   - Выберите "Windows PowerShell (Администратор)" или "Командная строка (Администратор)"

2. Запустите MySQL:
   ```bash
   C
   ```
   
   Или если служба называется по-другому:
   ```bash
   net start MySQL80
   net start MySQL57
   net start "MySQL Server 8.0"
   ```

3. Чтобы остановить MySQL:
   ```bash
   net stop MySQL
   ```

## Способ 2: Через службы Windows

1. Нажмите `Win + R`
2. Введите `services.msc` и нажмите Enter
3. Найдите службу MySQL (может называться "MySQL", "MySQL80", "MySQL Server 8.0" и т.д.)
4. Правой кнопкой мыши → "Запустить" или "Start"

## Способ 3: Через диспетчер задач

1. Откройте Диспетчер задач (`Ctrl + Shift + Esc`)
2. Перейдите на вкладку "Службы"
3. Найдите MySQL и нажмите "Запустить"

## Способ 4: Если используете XAMPP/WAMP

- **XAMPP**: Запустите XAMPP Control Panel → Нажмите "Start" рядом с MySQL
- **WAMP**: Кликните на иконку WAMP → MySQL → Service → Start/Resume Service

## Проверка запущенного MySQL

После запуска проверьте, работает ли MySQL:

```bash
mysql -u root -p
```

Введите пароль (если установлен) или просто нажмите Enter.

Если MySQL запущен, вы увидите приглашение:
```
mysql>
```

## Поиск названия службы MySQL

Чтобы узнать точное название службы MySQL:

1. Откройте PowerShell от администратора
2. Выполните:
   ```powershell
   Get-Service | Where-Object {$_.DisplayName -like "*MySQL*"}
   ```

Вы увидите название службы, которую нужно запустить.

## Автозапуск MySQL

Чтобы MySQL запускался автоматически при включении компьютера:

1. Откройте `services.msc`
2. Найдите службу MySQL
3. Двойной клик → "Тип запуска" → "Автоматически"
4. Нажмите "OK"

## Если MySQL не установлен

Если MySQL не установлен, вам нужно:

1. Скачать MySQL с официального сайта: https://dev.mysql.com/downloads/installer/
2. Или использовать XAMPP: https://www.apachefriends.org/
3. Или установить через Docker (если установлен)

## Проверка подключения к MySQL из Python

После запуска MySQL, проверьте подключение:

```bash
python init_db.py
```

Если всё настроено правильно, вы увидите:
```
Database initialized successfully!
```
