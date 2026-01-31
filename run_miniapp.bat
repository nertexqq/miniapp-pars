@echo off
REM Запуск Mini App сервера на порту 5001
echo Starting Portals Gifts Mini App server...
echo Open browser: http://localhost:5001
echo.
cd /d "%~dp0miniapp"
python server.py
pause
