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

echo [0/4] 이전 산출물 정리 (실행 중이면 종료)...
taskkill /F /T /IM rsCommand.exe >nul 2>nul
ping -n 2 127.0.0.1 >nul
rmdir /s /q build >nul 2>nul
rmdir /s /q dist >nul 2>nul
if exist "dist\rsCommand.exe" (
    echo [오류] 기존 dist\rsCommand.exe 를 삭제하지 못했습니다(파일 잠김^).
    echo        - 실행 중인 rsCommand.exe 를 종료하세요(작업 관리자^).
    echo        - 백신이 dist 폴더를 잠글 수 있습니다(빌드 폴더 예외 추가^).
    pause
    exit /b 1
)

echo [1/4] 가상환경 생성...
python -m venv .buildvenv
if errorlevel 1 (
    echo venv 생성 실패
    pause
    exit /b 1
)

echo [2/4] 의존성 설치...
call .buildvenv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
if errorlevel 1 (
    echo 의존성 설치 실패
    pause
    exit /b 1
)

echo [3/4] 실행파일 빌드...
pyinstaller --clean -y --onefile --windowed --name rsCommand --hidden-import pyte main.py
if errorlevel 1 (
    echo 빌드 실패
    echo   - rsCommand.exe 가 실행 중이면 종료 후 다시 시도하세요.
    echo   - 백신이 dist 폴더를 잠글 수 있습니다(빌드 폴더 예외 추가 권장).
    pause
    exit /b 1
)

echo.
echo [4/4] 빌드 완료: dist\rsCommand.exe
pause
