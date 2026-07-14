#!/usr/bin/env bash
# 리눅스용 단일 실행파일(rsCommand) 빌드.
# ※ 반드시 "리눅스에서" 실행해야 합니다 (PyInstaller 는 크로스 컴파일 불가).
# ※ 배포 대상 중 가장 오래된 배포판에서 빌드해야 glibc 호환성이 좋습니다.
set -e
cd "$(dirname "$0")"

# 빌드 산출물/작업 폴더는 홈(실행 가능 경로)에 둔다.
# (Samba 공유는 noexec 로 마운트돼 실행이 막히는 경우가 많음)
BUILD="$HOME/rscommand-build"
VENV="$BUILD/venv"

python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip
pip install -r requirements-dev.txt

pyinstaller --clean -y \
    --onefile --windowed \
    --name rsCommand \
    --hidden-import pyte \
    --distpath "$BUILD/dist" \
    --workpath "$BUILD/work" \
    --specpath "$BUILD" \
    main.py

echo
echo "빌드 완료: $BUILD/dist/rsCommand"
echo "실행: $BUILD/dist/rsCommand"
echo "  (실행 시 xcb 라이브러리 필요: sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0)"
