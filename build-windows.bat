@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [오류] python 을 찾을 수 없습니다.
    echo        python.org 에서 Python 3.11+ 설치 시 "Add python.exe to PATH" 를 체크하고
    echo        새 명령 프롬프트에서 다시 실행하세요.
    pause
    exit /b 1
)

echo [1/3] 가상환경 생성...
python -m venv .buildvenv
if errorlevel 1 (
    echo venv 생성 실패
    pause
    exit /b 1
)

echo [2/3] 의존성 설치...
call .buildvenv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
if errorlevel 1 (
    echo 의존성 설치 실패
    pause
    exit /b 1
)

echo [3/3] 실행파일 빌드...
pyinstaller --clean -y --onefile --windowed --name rsCommand --hidden-import pyte main.py
if errorlevel 1 (
    echo 빌드 실패
    pause
    exit /b 1
)

echo.
echo 빌드 완료: dist\rsCommand.exe
pause
