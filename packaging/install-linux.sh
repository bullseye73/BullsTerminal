#!/usr/bin/env bash
# 우분투(그 외 freedesktop 계열)에 bullsTerminal 을 현재 사용자로 설치한다.
#   - 실행파일 → ~/.local/bin/bullsTerminal
#   - 아이콘   → ~/.local/share/icons/hicolor/{scalable,256x256}/apps/bullsterminal.*
#   - 실행기   → ~/.local/share/applications/bullsTerminal.desktop
#
# 사용법:  ./packaging/install-linux.sh [빌드_산출물_경로]
#          (생략 시 ~/bullsterminal-build/dist/bullsTerminal 사용)
#          onefile 산출물(파일)과 onedir 산출물(폴더) 모두 받습니다.
set -e
cd "$(dirname "$0")/.."
ROOT="$PWD"

SRC="${1:-$HOME/bullsterminal-build/dist/bullsTerminal}"
if [ ! -e "$SRC" ]; then
    echo "[오류] 빌드 산출물을 찾을 수 없습니다: $SRC"
    echo "       먼저 ./build-linux.sh 로 빌드하거나 경로를 인자로 넘기세요."
    exit 1
fi

BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/lib/bullsTerminal"
ICON_DIR="$HOME/.local/share/icons/hicolor"
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$BIN_DIR" "$APP_DIR" \
         "$ICON_DIR/scalable/apps" "$ICON_DIR/256x256/apps"

if [ -d "$SRC" ]; then
    # onedir: 폴더를 통째로 ~/.local/lib 에 두고 ~/.local/bin 에 링크
    if [ ! -x "$SRC/bullsTerminal" ]; then
        echo "[오류] 실행파일이 없습니다: $SRC/bullsTerminal"
        exit 1
    fi
    rm -rf "$LIB_DIR"
    mkdir -p "$(dirname "$LIB_DIR")"
    cp -a "$SRC" "$LIB_DIR"
    ln -sfn "$LIB_DIR/bullsTerminal" "$BIN_DIR/bullsTerminal"
    echo "설치 형태: onedir ($LIB_DIR)"
else
    # onefile: 실행파일 하나만 복사 (이전 onedir 설치 흔적/심볼릭 링크 제거 후)
    rm -rf "$LIB_DIR"
    rm -f "$BIN_DIR/bullsTerminal"
    install -m 755 "$SRC" "$BIN_DIR/bullsTerminal"
    echo "설치 형태: onefile"
fi
install -m 644 "$ROOT/assets/bullsterminal.svg" "$ICON_DIR/scalable/apps/bullsterminal.svg"
install -m 644 "$ROOT/assets/bullsterminal.png" "$ICON_DIR/256x256/apps/bullsterminal.png"

# Exec 은 설치 경로로 바꿔 절대 경로로 기록한다.
sed "s|^Exec=.*|Exec=$BIN_DIR/bullsTerminal|" \
    "$ROOT/packaging/bullsTerminal.desktop" > "$APP_DIR/bullsTerminal.desktop"
chmod 644 "$APP_DIR/bullsTerminal.desktop"

command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" || true
command -v gtk-update-icon-cache   >/dev/null && gtk-update-icon-cache -f -t "$ICON_DIR" >/dev/null 2>&1 || true

echo "설치 완료:"
echo "  실행파일 : $BIN_DIR/bullsTerminal"
echo "  실행기   : $APP_DIR/bullsTerminal.desktop"
echo "  아이콘   : $ICON_DIR/{scalable,256x256}/apps/bullsterminal.*"
echo
echo "'$BIN_DIR' 가 PATH 에 없다면 ~/.profile 에 다음을 추가하세요:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
