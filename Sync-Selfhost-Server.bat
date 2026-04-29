@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "SYNC_SCRIPT=%REPO_ROOT%tools\sync_selfhost_server.ps1"

if not exist "%SYNC_SCRIPT%" (
  echo sync_selfhost_server.ps1 not found:
  echo   %SYNC_SCRIPT%
  pause
  exit /b 1
)

set "SERVER_HOST=plm.xuebao.chat"
set "SERVER_USER=root"
set "SSH_PORT=22"
set "REMOTE_ROOT=/root/xuebao"

echo.
echo Deploy target:
echo   Host: %SERVER_HOST%
echo   User: %SERVER_USER%
echo   Port: %SSH_PORT%
echo   Path: %REMOTE_ROOT%
echo   Auth: project SSH key, defaults to ~/.ssh/xuebao_selfhost_ed25519 then ~/.ssh/learningpyramid_selfhost_ed25519
echo.

powershell -ExecutionPolicy Bypass -File "%SYNC_SCRIPT%" -ServerHost "%SERVER_HOST%" -ServerUser "%SERVER_USER%" -SshPort %SSH_PORT% -RemoteRoot "%REMOTE_ROOT%" -PromptOnDirtyWorktree %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo Deploy failed with exit code %EXIT_CODE%.
  pause
  exit /b %EXIT_CODE%
)

echo Deploy finished successfully.
pause
exit /b 0
