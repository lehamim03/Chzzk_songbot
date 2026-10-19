@echo off
chcp 65001 > nul
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo [처음 실행] 필요한 프로그램을 설치합니다. 1~2분 걸려요...
  python -m venv .venv
  if errorlevel 1 (
    echo Python 3.10 이상을 먼저 설치해 주세요: https://www.python.org/downloads/
    echo 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
    pause
    exit /b 1
  )
  .venv\Scripts\python -m pip install -q -r requirements.txt
)

if not exist config.json copy config.example.json config.json > nul

.venv\Scripts\python main.py
pause
