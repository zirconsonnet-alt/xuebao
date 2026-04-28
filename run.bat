@echo off
setlocal

cd /d I:\Projects\xuebao || exit /b 1

echo === Starting bot using Poetry venv ===
poetry run python bot.py

endlocal
