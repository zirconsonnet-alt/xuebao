@echo off
setlocal

cd /d %~dp0 || exit /b 1

echo === Step 1: Ensure Poetry exists ===
where poetry >nul 2>&1
if errorlevel 1 (
  echo Poetry not found, installing...
  python -m pip install -U poetry || exit /b 1
)

echo === Step 2: Force venv in .venv ===
poetry config --local virtualenvs.in-project true || exit /b 1

echo === Step 3: Update lock file ===
poetry lock || exit /b 1

echo === Step 4: Sync dependencies from lock ===
poetry sync --no-interaction || exit /b 1

echo === Done ===
poetry env info -p

endlocal
