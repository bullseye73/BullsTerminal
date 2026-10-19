#!/usr/bin/env bash
# macOS용 bullsTerminal.app 번들 빌드 스크립트.
#   ./build-macos.sh
# 산출물: dist/bullsTerminal.app
# ※ 반드시 macOS 환경에서 실행해야 합니다 (PyInstaller는 크로스 컴파일 불가).
set -e
cd "$(dirname "$0")"
ROOT="$PWD"

echo "=== [bullsTerminal macOS 앱 빌드 시작] ==="

# 1. 파이썬 환경 확인
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
    echo "[오류] $PYTHON 을 찾을 수 없습니다."
    echo "       brew install python 또는 python.org 에서 Python 3.10+ 설치 후 다시 시도하세요."
    exit 1
fi

VENV="$ROOT/.venv"
if [ ! -d "$VENV" ]; then
    echo "[1/4] 가상환경 생성 (.venv)..."
    "$PYTHON" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "[2/4] 의존성 설치 및 확인..."
pip install --upgrade pip >/dev/null
pip install -r requirements-dev.txt

# 2. macOS용 아이콘 (.icns) 준비
if [ ! -f "assets/bullsterminal.icns" ]; then
    echo "[*] macOS 앱 아이콘(assets/bullsterminal.icns) 생성 중..."
    python tools/make_icon.py
fi

ICON_ARG=()
if [ -f "assets/bullsterminal.icns" ]; then
    ICON_ARG=(--icon "$ROOT/assets/bullsterminal.icns")
fi

# 3. 불필요한 대형 Qt 모듈 제외 (번들 크기 최소화)
EXCLUDES=()
for m in QtQml QtQuick QtQuick3D QtQuickWidgets QtQuickControls2 QtQuickTest \
         QtWebEngineCore QtWebEngineWidgets QtWebEngineQuick QtWebChannel QtWebSockets \
         Qt3DCore Qt3DRender Qt3DAnimation Qt3DInput Qt3DLogic Qt3DExtras \
         QtCharts QtDataVisualization QtGraphs QtMultimedia QtMultimediaWidgets \
         QtSpatialAudio QtTextToSpeech QtBluetooth QtNfc QtPositioning QtLocation \
         QtSensors QtSerialPort QtSerialBus QtRemoteObjects QtScxml QtStateMachine \
         QtDesigner QtUiTools QtHelp QtTest QtSql QtPdf QtPdfWidgets; do
    EXCLUDES+=(--exclude-module "PySide6.$m")
done

echo "[3/4] bullsTerminal.app 번들 패키징 (PyInstaller)..."
rm -rf build dist

pyinstaller --clean -y \
    --windowed \
    --name bullsTerminal \
    "${ICON_ARG[@]}" \
    --osx-bundle-identifier "com.bullseye.bullsterminal" \
    --hidden-import pyte \
    --add-data "$ROOT/assets:assets" \
    "${EXCLUDES[@]}" \
    --distpath "$ROOT/dist" \
    --workpath "$ROOT/build" \
    main.py

# 4. Ad-hoc 로컬 서명 적용
if [ -d "$ROOT/dist/bullsTerminal.app" ]; then
    echo "[4/4] 로컬 실행 코드 서명 적용..."
    codesign --force --deep -s - "$ROOT/dist/bullsTerminal.app" 2>/dev/null || true
fi

echo
echo "================================================================="
echo " 빌드 성공! 산출물: dist/bullsTerminal.app"
echo "================================================================="
echo " 1. 즉시 실행:"
echo "    open dist/bullsTerminal.app"
echo
echo " 2. Applications 폴더로 설치:"
echo "    cp -R dist/bullsTerminal.app /Applications/"
echo
echo " ※ 게이트키퍼(개발자 미확인) 보안 경고 발생 시:"
echo "    xattr -cr dist/bullsTerminal.app"
echo "================================================================="
