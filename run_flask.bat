@echo off
setlocal

cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set SETUP_MARKER=.venv\.fitai_setup_done

echo ==========================================
echo     FitAI start: %date% %time%
echo ==========================================
echo.

:: =========================
:: VIRTUAL ENV
:: =========================
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>&1

    if errorlevel 1 (
        echo [INFO] Virtualne prostredie je poskodene, vytvaram ho nanovo...
        rmdir /s /q ".venv"
    )
)

if not exist ".venv" (
    echo [INFO] Vytvaram virtualne prostredie...
    python -m venv .venv

    echo.
    echo [INFO] Upgradujem pip...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)

if not exist "%SETUP_MARKER%" (
    echo.
    echo [INFO] Prva instalacia kniznic. Toto moze chvilu trvat...

    if exist "requirements.txt" (
        ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    ) else (
        ".venv\Scripts\python.exe" -m pip install Flask flask_sqlalchemy flask_bcrypt flask_login flask_wtf wtforms email-validator google-generativeai python-dotenv
    )

    if errorlevel 1 (
        echo.
        echo [CHYBA] Instalacia kniznic zlyhala.
        pause
        exit /b 1
    )

    echo setup-ok > "%SETUP_MARKER%"
) else (
    echo [INFO] Kniznice uz su pripravene, preskakujem instalaciu.
)

:: =========================
:: RUN APP
:: =========================
echo.
echo ==========================================
echo    Server bezi na: http://127.0.0.1:5000
echo ==========================================
echo.
echo Ak sa stranka neotvori sama, otvor v prehliadaci:
echo http://127.0.0.1:5000
echo.

start "" http://127.0.0.1:5000
".venv\Scripts\python.exe" main.py

if errorlevel 1 (
    echo.
    echo [CHYBA] Server padol.
    pause
)


