@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0_copilot_home.bat" (
  echo [ERROR] Missing _copilot_home.bat - run scripts\init_data_repo.bat in the code repo first.
  exit /b 1
)
call "%~dp0_copilot_home.bat"
set "DATA_DIR=%~dp0"
set "PYTHONPATH=%COPILOT_HOME%"
if not exist "%COPILOT_HOME%\.venv\Scripts\python.exe" (
  echo [ERROR] Not found: %COPILOT_HOME%\.venv\Scripts\python.exe
  echo         Create the venv in the code repo first - see README.
  exit /b 1
)
"%COPILOT_HOME%\.venv\Scripts\python.exe" -m copilot.main %*
exit /b %ERRORLEVEL%
