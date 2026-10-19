@echo off
rem Keep this file ASCII-only with CRLF line endings (cmd.exe misreads UTF-8/LF batch files).
cd /d "%~dp0"

if exist .venv\Scripts\python.exe goto config

echo [First run] Installing required packages. This takes 1-2 minutes...
python -m venv .venv
if errorlevel 1 goto nopython
.venv\Scripts\python -m pip install -q -r requirements.txt
if errorlevel 1 goto pipfail

:config
if not exist config.json copy config.example.json config.json > nul

.venv\Scripts\python main.py
pause
exit /b

:nopython
echo.
echo Python 3.10 or newer is required: https://www.python.org/downloads/
echo When installing, check "Add python.exe to PATH".
pause
exit /b 1

:pipfail
echo.
echo Package installation failed. Check your internet connection and run again.
rmdir /s /q .venv
pause
exit /b 1
