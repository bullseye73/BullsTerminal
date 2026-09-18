#!/usr/bin/env bash
# 리눅스용 실행파일(bullsTerminal) 빌드.
#   ./build-linux.sh            # onefile: 단일 실행파일(실행할 때마다 $TMPDIR 에 압축 해제)
#   ./build-linux.sh --onedir   # onedir : 폴더 배포(해제 과정 없음 → 시작 빠르고 /tmp 공간 불필요)
# ※ 반드시 "리눅스에서" 실행해야 합니다 (PyInstaller 는 크로스 컴파일 불가).
# ※ 배포 대상 중 가장 오래된 배포판에서 빌드해야 glibc 호환성이 좋습니다.
set -e
cd "$(dirname "$0")"
ROOT="$PWD"

MODE="onefile"
case "${1:-}" in
    ""|--onefile|onefile) ;;
    --onedir|onedir) MODE="onedir" ;;
    *)
        echo "사용법: $0 [--onefile|--onedir]"
        exit 1
        ;;
esac

# 빌드 산출물/작업 폴더는 홈(실행 가능 경로)에 둔다.
# (Samba 공유는 noexec 로 마운트돼 실행이 막히는 경우가 많음)
BUILD="$HOME/bullsterminal-build"
VENV="$BUILD/venv"
OUT="$BUILD/dist/bullsTerminal"

python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip
pip install -r requirements-dev.txt

# 이 앱은 QtCore/QtGui/QtWidgets 만 사용한다. PySide6-Addons 의 Qml/Quick/WebEngine/3D 등
# 대형 모듈을 빼면 번들 크기가 크게 줄고, onefile 실행 시 임시폴더 압박도 줄어든다.
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

# --add-data 의 원본 경로는 --specpath(= $BUILD) 기준으로 해석되므로 절대경로로 준다.
pyinstaller --clean -y \
    "--$MODE" --windowed \
    --name bullsTerminal \
    --hidden-import pyte \
    --add-data "$ROOT/assets:assets" \
    "${EXCLUDES[@]}" \
    --distpath "$BUILD/dist" \
    --workpath "$BUILD/work" \
    --specpath "$BUILD" \
    main.py

echo
if [ "$MODE" = "onedir" ]; then
    echo "빌드 완료(onedir): $OUT/"
    echo "실행: $OUT/bullsTerminal"
    echo "  배포할 때는 폴더를 통째로(내부 _internal 포함) 복사하세요."
else
    echo "빌드 완료(onefile): $OUT"
    echo "실행: $OUT"
    echo
    echo "※ onefile 은 실행할 때마다 \$TMPDIR(기본 /tmp)에 Qt 전체를 풉니다."
    echo "   'Failed to extract ...: decompression resulted in return code -1' 은"
    echo "   임시 공간 부족/쓰기 실패입니다. 다음을 확인하세요:"
    echo "     df -h /tmp                  # 남은 용량 확인"
    echo "     rm -rf /tmp/_MEI*           # 실패한 실행이 남긴 찌꺼기 정리"
    echo "     TMPDIR=\$HOME/.cache $OUT   # 여유 있는 다른 위치에 해제"
    echo "   또는 './build-linux.sh --onedir' 로 빌드하면 해제 과정 자체가 없습니다."
fi
echo
echo "  (실행 시 xcb 라이브러리 필요: sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0)"
echo "메뉴 등록(아이콘/바로가기): ./packaging/install-linux.sh \"$OUT\""
