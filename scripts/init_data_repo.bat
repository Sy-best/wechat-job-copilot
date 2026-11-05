@echo off
chcp 65001 >nul
setlocal

rem Code repo root - this script lives in scripts\
for %%i in ("%~dp0..") do set "CODE_DIR=%%~fi"
set "TPL=%CODE_DIR%\templates\data-repo"

rem Data repo location - defaults to a sibling dir, or pass one as the first arg
set "DATA_DIR=%~1"
if "%DATA_DIR%"=="" set "DATA_DIR=%CODE_DIR%\..\wechat-job-data"
for %%i in ("%DATA_DIR%") do set "DATA_DIR=%%~fi"

echo ============================================================
echo  Create private data repo skeleton
echo   CODE_DIR : %CODE_DIR%
echo   DATA_DIR : %DATA_DIR%
echo ============================================================
if not exist "%TPL%\run.bat" (
  echo [ERROR] Template dir not found: %TPL%
  exit /b 1
)

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%DATA_DIR%\contacts" mkdir "%DATA_DIR%\contacts"
if not exist "%DATA_DIR%\notes" mkdir "%DATA_DIR%\notes"
if not exist "%DATA_DIR%\logs" mkdir "%DATA_DIR%\logs"

rem Launchers, docs and gitignore - never overwrite existing files
for %%f in (run.bat start.bat start_auto.bat doctor.bat README.md DO_NOT_PUSH.md) do (
  if not exist "%DATA_DIR%\%%f" copy /y "%TPL%\%%f" "%DATA_DIR%\%%f" >nul
)
if not exist "%DATA_DIR%\.gitignore" copy /y "%TPL%\gitignore.template" "%DATA_DIR%\.gitignore" >nul

rem Blank templates - never overwrite real data
if not exist "%DATA_DIR%\.env" copy /y "%CODE_DIR%\.env.example" "%DATA_DIR%\.env" >nul
if not exist "%DATA_DIR%\ai_provider.env" copy /y "%CODE_DIR%\ai_provider.env.example" "%DATA_DIR%\ai_provider.env" >nul
if not exist "%DATA_DIR%\口径包.md" copy /y "%CODE_DIR%\copilot\口径包.example.md" "%DATA_DIR%\口径包.md" >nul
if not exist "%DATA_DIR%\examples.md" copy /y "%CODE_DIR%\copilot\examples.example.md" "%DATA_DIR%\examples.md" >nul
if not exist "%DATA_DIR%\contacts\README.md" copy /y "%CODE_DIR%\copilot\contacts\README.md" "%DATA_DIR%\contacts\README.md" >nul

rem Remember where the code repo lives - local path only, gitignored
> "%DATA_DIR%\_copilot_home.bat" echo @echo off
>> "%DATA_DIR%\_copilot_home.bat" echo set "COPILOT_HOME=%CODE_DIR%"

rem Bootstrap config in the code repo - one line, already gitignored here
if not exist "%CODE_DIR%\.env" (
  > "%CODE_DIR%\.env" echo DATA_DIR=%DATA_DIR%
)

echo.
echo [OK] Data repo skeleton ready: %DATA_DIR%
echo.
echo Next steps:
echo   1. Fill %DATA_DIR%\ai_provider.env
echo      AI_API_KEY / AI_BASE_URL / AI_MODEL - see comments in the template
echo   2. Optionally fill %DATA_DIR%\.env
echo      WECHAT_DB_DIR blank = auto detect, WATCH_CHATS blank = watch all
echo   3. After installing the venv in the code repo, run:
echo      .venv\Scripts\python.exe -m copilot.main doctor
echo   4. Double-click %DATA_DIR%\start.bat - human-confirm mode, recommended
echo.
echo [WARNING] This directory holds private chats and API keys.
echo     NEVER push it, make it public, or put it in a cloud sync folder.
echo     See %DATA_DIR%\DO_NOT_PUSH.md
echo.
endlocal
