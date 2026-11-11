"""pyte 기반 대화형 터미널 위젯.

Paramiko 대화형 셸 채널에 키 입력을 보내고, 출력 바이트를 pyte 화면
에뮬레이터로 파싱해 격자 형태로 렌더링한다. (vim/htop/색상 대응)
- 스크롤백(과거 로그) 지원: HistoryScreen + 세로 스크롤바 / 휠 / Shift+PgUp·PgDn
- 마우스 드래그 선택 + 복사/붙여넣기
- 각 위젯은 자신의 SSH 연결을 소유
"""
from __future__ import annotations

import codecs
import copy
import itertools
import re
import queue
import socket
import threading
import time
import urllib.parse
from typing import List, Optional, Tuple

import pyte
from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QClipboard, QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QScrollBar,
    QWidget,
)

# ANSI 기본 8색 (dark/bright)
_BASE = {
    "black": "#2e3436", "red": "#cc0000", "green": "#4e9a06", "brown": "#c4a000",
    "blue": "#3465a4", "magenta": "#75507b", "cyan": "#06989a", "white": "#d3d7cf",
}
_BRIGHT = {
    "black": "#555753", "red": "#ef2929", "green": "#8ae234", "brown": "#fce94f",
    "blue": "#729fcf", "magenta": "#ad7fa8", "cyan": "#34e2e2", "white": "#eeeeec",
}
_DEFAULT_FG = "#e4e4e7"
_DEFAULT_BG = "#141417"
_SEL_BG = "#2b426b"
_HISTORY_LINES = 5000
# pyte 는 private 모드를 (mode << 5) 로 저장. DECCKM(애플리케이션 커서 키)=모드 1.
_DECCKM = 1 << 5

# pyte 파서는 순수 파이썬이라 느림(≈300KB/s). 파싱은 리더 스레드에서 수행하고
# GUI 는 락 하에 화면을 읽어 페인트만 한다(_feed/paintEvent). GIL 이 주기적으로
# 양보되므로 대량 출력에도 UI 가 막히지 않고, recv→feed 순차 처리로 SSH
# 백프레셔가 걸려 데이터 폐기 없이 완전 보존된다.

# ANSI 이스케이프 시퀀스 제거(세션 로그용)
_ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC
    r"|\x1b[P^_X][^\x1b]*\x1b\\"           # DCS/PM/APC/SOS
    r"|\x1b\[[0-9;?<>=!]*[ -/]*[@-~]"      # CSI
    r"|\x1b[@-Z\\-_]"                       # 2문자 ESC 시퀀스
)
# 개행/탭 제외 제어문자 제거
_CTRL_STRIP = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class _SessionLog:
    """수신 바이트에서 ANSI/제어문자를 제거해 텍스트로 파일에 실시간 기록.

    화면 스크롤백(5000줄) 한도와 무관하게, 로그 시작 이후 모든 출력을 저장한다.
    """

    _FLUSH_BYTES = 32768  # 이만큼 쌓이면 flush (매 청크 flush 방지)

    def __init__(self, fh) -> None:
        self._fh = fh
        self._dec = codecs.getincrementaldecoder("utf-8")("replace")
        self._pending = ""
        self._unflushed = 0

    def feed(self, data: bytes) -> None:
        text = self._pending + self._dec.decode(data)
        # 마지막 ESC 가 아직 미완성 시퀀스면 다음 데이터까지 보류(경계 처리)
        idx = text.rfind("\x1b")
        if idx != -1 and _ANSI_RE.search(text, idx) is None:
            self._pending = text[idx:]
            text = text[:idx]
        else:
            self._pending = ""
        text = _ANSI_RE.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _CTRL_STRIP.sub("", text)
        if not text:
            return
        try:
            self._fh.write(text)
            self._unflushed += len(text)
            if self._unflushed >= self._FLUSH_BYTES:
                self._fh.flush()
                self._unflushed = 0
        except Exception:
            pass

    def idle_flush(self) -> None:
        """유휴 시(출력 소강) 남은 데이터를 디스크에 반영."""
        if self._unflushed:
            try:
                self._fh.flush()
            except Exception:
                pass
            self._unflushed = 0

    def write_raw(self, text: str) -> None:
        """이미 정제된 텍스트(현재 스크롤백 등)를 그대로 기록."""
        try:
            self._fh.write(text)
            self._unflushed += len(text)
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._pending:
                self._fh.write(_ANSI_RE.sub("", self._pending))
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass

Cell = Tuple[int, int]  # (row, col)


_COLOR_CACHE: dict = {}  # (color, default_hex, bright) -> QColor (읽기전용 공유)


def _resolve(color: str, default_hex: str, bright: bool = False) -> QColor:
    key = (color, default_hex, bright)
    cached = _COLOR_CACHE.get(key)
    if cached is not None:
        return cached
    result = _resolve_uncached(color, default_hex, bright)
    _COLOR_CACHE[key] = result
    return result


def _resolve_uncached(color: str, default_hex: str, bright: bool) -> QColor:
    if color == "default":
        return QColor(default_hex)
    name = color
    if name.startswith("bright"):
        name = name[6:]
        bright = True
    if name in _BASE:
        return QColor((_BRIGHT if bright else _BASE)[name])
    if len(color) == 6:  # 256/truecolor -> hex 문자열
        c = QColor("#" + color)
        if c.isValid():
            return c
    return QColor(default_hex)


class _Reader(QThread):
    """채널을 읽어 세션 로그 기록 + pyte 파싱(sink)을 모두 이 워커 스레드에서 수행.

    파싱을 GUI 밖으로 빼서 대량 출력에도 UI가 막히지 않게 한다. recv→sink 를
    순차로 처리하므로, 파싱이 느리면 recv 가 자연히 느려져 SSH 백프레셔가 걸린다
    (데이터 폐기 없이 완전 보존).
    """

    closed = Signal()

    def __init__(self, channel, sink) -> None:
        super().__init__()
        self._channel = channel
        self._sink = sink  # 위젯의 _feed(chunk): 락 하에 pyte.feed
        self._run = True
        self._log: Optional[_SessionLog] = None
        self._log_lock = threading.Lock()

    def set_log(self, log: "Optional[_SessionLog]") -> "Optional[_SessionLog]":
        """세션 로그를 교체하고 이전 로그를 반환(호출자가 close)."""
        with self._log_lock:
            old = self._log
            self._log = log
        return old

    def run(self) -> None:
        self._channel.settimeout(0.05)
        while self._run:
            try:
                chunk = self._channel.recv(65536)
            except socket.timeout:
                with self._log_lock:
                    if self._log is not None:
                        self._log.idle_flush()
                continue
            except Exception:
                break
            if not chunk:
                break
            with self._log_lock:
                if self._log is not None:
                    self._log.feed(chunk)
            self._sink(chunk)  # pyte 파싱(위젯 락 하에)
        with self._log_lock:
            if self._log is not None:
                self._log.close()
                self._log = None
        self.closed.emit()

    def stop(self) -> None:
        self._run = False


class _Writer(threading.Thread):
    """키 입력/붙여넣기/명령을 채널로 보내는 전용 스레드.

    channel.send() 는 SSH 윈도우가 차면 일부만 보내거나 대기한다. GUI 스레드에서
    직접 부르면 (1) 반환값을 무시해 큰 붙여넣기가 잘리고 (2) 서버가 읽지 않을 때
    UI 가 멈춘다. 큐에 넣고 여기서 남김없이 순서대로 보낸다.
    """

    def __init__(self, channel) -> None:
        super().__init__(daemon=True, name="bt-term-writer")
        self._channel = channel
        self._queue: "queue.Queue" = queue.Queue()
        self._run = True

    def write(self, data: bytes) -> None:
        if data and self._run:
            self._queue.put(data)

    def stop(self) -> None:
        self._run = False
        self._queue.put(None)

    def run(self) -> None:
        while self._run:
            data = self._queue.get()
            if data is None:
                break
            view = bytes(data)
            while view and self._run:
                try:
                    sent = self._channel.send(view[:32768])
                except socket.timeout:
                    continue  # 윈도우가 열릴 때까지 재시도(리더가 채널 타임아웃을 짧게 둠)
                except Exception:
                    return  # 채널 종료
                if sent <= 0:
                    return
                view = view[sent:]


# pyte 는 private 모드를 (mode << 5) 로 저장. 2004 = 브래킷 붙여넣기.
_BRACKETED_PASTE = 2004 << 5
_PASTE_START = "\x1b[200~"
_PASTE_END = "\x1b[201~"
# 붙여넣기에서 제거할 제어문자(탭/개행 제외). ESC 를 지우면 숨은 이스케이프 시퀀스도 무력화된다.
_PASTE_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 셸 프롬프트로 보이는 줄 끝($ # %). psql 의 'db=#' 같은 REPL 프롬프트는 제외.
_PROMPT_END = re.compile(r"(?<![=>])[$#%]$")


def sanitize_paste(text: str) -> str:
    """붙여넣을 텍스트 정리: 줄바꿈 통일, 제어문자(ESC 포함) 제거."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _PASTE_CTRL.sub("", text)


# 종료 대기 시간 안에 끝나지 않은 리더 스레드 보관(실행 중 QThread 파괴 → 크래시 방지)
_ORPHAN_READERS: set = set()


class TerminalScreen(pyte.HistoryScreen):
    """pyte HistoryScreen + 대체 화면(alternate screen) 지원.

    pyte 는 대체 화면(mode 47/1047/1049)을 구현하지 않아 vim/less/htop 등
    전체화면 앱이 스크롤백을 오염시키고 화면이 어긋난다. 진입 시 현재 버퍼를
    저장하고 깨끗한 화면으로 전환, 종료 시 복원하며, 대체 화면 동안에는
    스크롤백(히스토리)에 줄을 쌓지 않는다.
    """

    def __init__(self, columns, lines, history=5000, ratio=0.5) -> None:
        super().__init__(columns, lines, history=history, ratio=ratio)
        self.in_alt = False
        self._saved_buffer = None
        self._saved_cursor = None

    def _enter_alt(self) -> None:
        if self.in_alt:
            return
        self.in_alt = True
        self._saved_buffer = copy.deepcopy(self.buffer)
        self._saved_cursor = copy.copy(self.cursor)
        self.buffer.clear()
        self.cursor.x = 0
        self.cursor.y = 0
        self.dirty.update(range(self.lines))

    def _leave_alt(self) -> None:
        if not self.in_alt:
            return
        self.in_alt = False
        if self._saved_buffer is not None:
            self.buffer.clear()
            self.buffer.update(self._saved_buffer)
        if self._saved_cursor is not None:
            self.cursor.x = self._saved_cursor.x
            self.cursor.y = self._saved_cursor.y
        self._saved_buffer = None
        self._saved_cursor = None
        self.dirty.update(range(self.lines))

    def set_mode(self, *modes, **kwargs) -> None:
        if kwargs.get("private") and (set(modes) & {47, 1047, 1049}):
            self._enter_alt()
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs) -> None:
        if kwargs.get("private") and (set(modes) & {47, 1047, 1049}):
            self._leave_alt()
        super().reset_mode(*modes, **kwargs)

    def index(self) -> None:
        # 대체 화면에서는 스크롤백에 줄을 쌓지 않음
        if self.in_alt:
            pyte.Screen.index(self)
        else:
            super().index()

    def reverse_index(self) -> None:
        if self.in_alt:
            pyte.Screen.reverse_index(self)
        else:
            super().reverse_index()


class TerminalWidget(QWidget):
    session_closed = Signal(object)      # 자기 자신을 전달
    cwd_changed = Signal(object, str)    # (self, path) OSC7 로 감지한 현재 경로

    def __init__(self, channel, client=None, font=None, parent=None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.client = client  # 이 터미널 전용 SSH 연결
        self._alive = True
        self.remote_cwd: Optional[str] = None   # OSC7 로 감지된 현재 원격 경로
        self._osc_pending = b""                  # OSC7 경계 분할 버퍼(리더 스레드)
        self._cwd_reporting = False              # OSC7 리포팅 주입 여부
        self._cwd_pending = False                # 프롬프트 대기 중인 주입 요청
        self._last_output = time.monotonic()     # 마지막 출력 수신 시각(리더 스레드가 갱신)

        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)  # IME(한글 등) 입력
        self.setCursor(Qt.IBeamCursor)

        if font is None:
            font = QFont("Monospace")
            font.setStyleHint(QFont.Monospace)
            font.setPointSize(12)
        self._font = QFont(font)
        self.setFont(self._font)
        self._recompute_metrics()

        self._cols = 80
        self._rows = 24
        self.screen = TerminalScreen(
            self._cols, self._rows, history=_HISTORY_LINES, ratio=0.5
        )
        self.stream = pyte.ByteStream(self.screen)

        # 스크롤바 (과거 로그)
        self._vbar = QScrollBar(Qt.Vertical, self)
        self._vbar.valueChanged.connect(self._on_scroll)
        self._sbw = self._vbar.sizeHint().width()
        self._follow = True  # 바닥 고정(자동 스크롤)
        self._view_rows: List[object] = []  # 마지막 렌더된 행(선택 추출용)

        # 선택 상태 (뷰포트 행 좌표)
        self._sel_start: Optional[Cell] = None
        self._sel_end: Optional[Cell] = None
        self._selecting = False

        self._dirty = False
        self._lock = threading.RLock()  # screen/stream 접근 보호(리더 스레드 ↔ GUI)
        self._log_path: Optional[str] = None
        self._flush_timer = QTimer(self)
        self._flush_timer.timeout.connect(self._tick)
        self._flush_timer.start(33)  # ~30fps 리페인트 구동

        self._writer = _Writer(channel)
        self._writer.start()
        self._reader = _Reader(channel, self._feed)
        self._reader.closed.connect(self._on_closed)
        self._reader.start()

    # ------------------------------------------------------------ 입출력
    def _feed(self, chunk: bytes) -> None:
        """리더 스레드에서 호출: pyte 파싱(락 보호). 작은 조각으로 나눠 락 점유를
        짧게 유지 → GUI 페인트가 조각 사이에 끼어들 수 있음."""
        self._last_output = time.monotonic()
        self._scan_osc7(chunk)  # 현재 경로(OSC7) 추적 (락 불필요, 화면과 무관)
        for i in range(0, len(chunk), 4096):
            with self._lock:
                try:
                    self.stream.feed(chunk[i:i + 4096])
                except Exception:
                    pass
            time.sleep(0)  # 락 공정성: 페인트/입력 스레드에 기회를 준다
        self._dirty = True

    # ------------------------------------------------------- 경로(OSC7) 추적
    def _scan_osc7(self, chunk: bytes) -> None:
        buf = self._osc_pending + chunk
        self._osc_pending = b""
        while True:
            i = buf.find(b"\x1b]7;")
            if i == -1:
                self._osc_pending = buf[-3:]  # 'ESC]7' 분할 대비 소량 보관
                return
            j_bel = buf.find(b"\x07", i + 4)
            j_st = buf.find(b"\x1b\\", i + 4)
            ends = [j for j in (j_bel, j_st) if j != -1]
            if not ends:
                self._osc_pending = buf[i:] if (len(buf) - i) <= 4096 else b""
                return
            end = min(ends)
            self._handle_osc7(buf[i + 4:end])
            buf = buf[end + (1 if end == j_bel else 2):]

    def _handle_osc7(self, payload: bytes) -> None:
        try:
            text = payload.decode("utf-8", "replace")
        except Exception:
            return
        if not text.startswith("file://"):
            return
        rest = text[len("file://"):]
        slash = rest.find("/")
        if slash == -1:
            return
        path = urllib.parse.unquote(rest[slash:])
        if path and path != self.remote_cwd:
            self.remote_cwd = path
            self.cwd_changed.emit(self, path)

    def enable_cwd_reporting(self) -> None:
        """프롬프트마다 현재 경로를 OSC7 로 보고하도록 셸에 1회 주입.

        bash 는 PROMPT_COMMAND 를 쓰지만, 임베디드(BusyBox ash/dash)는
        PROMPT_COMMAND 를 지원하지 않으므로 PS1 확장으로 폴백한다.
        (ash 의 PS1 파라미터 확장 기능이 켜져 있어야 함)
        """
        if self._cwd_reporting or not self._alive:
            return
        # 설정 명령은 '키 입력'으로 들어가므로, 셸 프롬프트가 아닐 때(vim, sudo 비밀번호
        # 입력, mysql 등) 보내면 그 프로그램에 타이핑된다. 프롬프트가 보일 때까지 미룬다.
        if not self._at_shell_prompt():
            self._cwd_pending = True
            return
        self._cwd_pending = False
        self._cwd_reporting = True
        # 한 번만 즉시 방출 + 프롬프트마다 방출 설정 (bash/ash 분기)
        emit = r'printf "\033]7;file://%s%s\a" "${HOSTNAME}" "$PWD"'
        bash_pc = (
            "PROMPT_COMMAND='" + emit + "'"
            + '"${PROMPT_COMMAND:+;$PROMPT_COMMAND}"'
        )
        # ash/sh: ESC/BEL 은 printf 로 만든 변수로 넣고, ${PWD}는 리터럴로 남겨
        # 프롬프트 표시 때 확장되게 한다(입력줄에 raw ESC 를 넣지 않음).
        ash_ps1 = (
            "__e=$(printf '\\033'); __b=$(printf '\\a'); "
            "PS1=${__e}']7;file://${HOSTNAME}${PWD}'${__b}\"$PS1\""
        )
        cmd = (
            ' if [ -n "$BASH_VERSION" ]; then ' + bash_pc
            + "; else " + ash_ps1 + "; fi; " + emit + "\r"
        )
        self.send_text(cmd)

    def cancel_cwd_reporting(self) -> None:
        """아직 보내지 않은(프롬프트 대기 중인) 경로 리포팅 설정 요청을 취소."""
        self._cwd_pending = False

    def _at_shell_prompt(self) -> bool:
        """화면 상태로 '빈 셸 프롬프트에서 대기 중'인지 추정(보수적)."""
        if time.monotonic() - self._last_output < 0.3:
            return False  # 출력이 아직 흐르는 중
        try:
            with self._lock:
                if self.screen.in_alt:
                    return False  # vim/less/htop 등 전체화면 프로그램
                cur = self.screen.cursor
                row = self.screen.buffer[cur.y]
                line = "".join(
                    (row[x].data or " ") for x in range(self.screen.columns)
                )
        except Exception:
            return False
        if line[cur.x:].strip():
            return False  # 커서 뒤에 글자가 있음(편집 중)
        head = line[:cur.x].rstrip()
        # 프롬프트 기호로 끝나야 함 = 사용자가 아직 아무것도 입력하지 않은 상태
        return bool(head) and bool(_PROMPT_END.search(head))

    def _on_closed(self) -> None:
        if not self._alive:
            return
        self._alive = False
        self._writer.stop()
        with self._lock:
            try:
                self.stream.feed(
                    "\r\n[\x1b[33m연결이 종료되었습니다\x1b[0m]\r\n".encode("utf-8")
                )
            except Exception:
                pass
        self._dirty = True
        self._log_path = None  # 리더가 종료되며 로그도 닫힘
        self.session_closed.emit(self)

    def _tick(self) -> None:
        """GUI 타이머: 변경 시 스크롤바 갱신 + 리페인트 예약."""
        if self._cwd_pending and self._alive:
            self.enable_cwd_reporting()  # 프롬프트가 보이면 그때 설정
        if self._dirty:
            self._dirty = False
            with self._lock:
                self._update_scrollbar()
            self.update()

    # -------------------------------------------------------------- 스크롤
    def _history_len(self) -> int:
        return len(self.screen.history.top)

    def _update_scrollbar(self) -> None:
        total = self._history_len()
        self._vbar.blockSignals(True)
        self._vbar.setRange(0, total)
        self._vbar.setPageStep(max(1, self._rows))
        self._vbar.setSingleStep(1)
        if self._follow:
            self._vbar.setValue(total)  # 바닥
        self._vbar.blockSignals(False)

    def _on_scroll(self, value: int) -> None:
        self._follow = value >= self._history_len()
        self.update()

    def _scroll_to_bottom(self) -> None:
        self._follow = True
        self._vbar.setValue(self._history_len())

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps:
            self._vbar.setValue(int(self._vbar.value() - steps * 3))

    # -------------------------------------------------------------- 폰트/크기
    def _recompute_metrics(self) -> None:
        fm = QFontMetricsF(self._font)
        self._cw = max(1.0, fm.horizontalAdvance("M"))
        self._ch = max(1.0, fm.height())
        self._ascent = fm.ascent()

    def apply_font(self, font) -> None:
        """폰트/크기 변경을 반영하고 셀 크기·pty 크기를 재계산."""
        self._font = QFont(font)
        self.setFont(self._font)
        self._recompute_metrics()
        cols = max(1, int(self._text_width() / self._cw))
        rows = max(1, int(self.height() / self._ch))
        self._cols, self._rows = cols, rows
        self._clear_selection()
        with self._lock:
            try:
                self.screen.resize(rows, cols)
            except Exception:
                pass
            self._update_scrollbar()
        if self._alive:
            try:
                self.channel.resize_pty(width=cols, height=rows)
            except Exception:
                pass
        self.update()

    def _text_width(self) -> int:
        return max(1, self.width() - self._sbw)

    def resizeEvent(self, event) -> None:
        self._vbar.setGeometry(self.width() - self._sbw, 0, self._sbw, self.height())
        cols = max(1, int(self._text_width() / self._cw))
        rows = max(1, int(self.height() / self._ch))
        if cols != self._cols or rows != self._rows:
            self._cols, self._rows = cols, rows
            self._clear_selection()
            with self._lock:
                try:
                    self.screen.resize(rows, cols)
                except Exception:
                    pass
            if self._alive:
                try:
                    self.channel.resize_pty(width=cols, height=rows)
                except Exception:
                    pass
            self._dirty = True
        with self._lock:
            self._update_scrollbar()
        super().resizeEvent(event)

    # -------------------------------------------------------------- 렌더
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(_DEFAULT_BG))
        p.setFont(self._font)

        cw, ch = self._cw, self._ch
        sel = self._ordered_selection()
        sel_bg = QColor(_SEL_BG)
        default_bg = QColor(_DEFAULT_BG)
        ascent = self._ascent
        view_texts: List[Optional[str]] = []

        # 화면 읽기·그리기는 락 하에서(리더 스레드의 pyte 파싱과 상호배제)
        with self._lock:
            cols = self.screen.columns
            history = self.screen.history.top
            nb_top = len(history)
            buffer = self.screen.buffer
            start = self._vbar.value()
            if start < nb_top:
                hist_rows = list(itertools.islice(history, start, start + self._rows))
            else:
                hist_rows = []
            cursor = self.screen.cursor
            show_cursor = (
                self._alive and not cursor.hidden and self.hasFocus() and self._follow
            )
            lines = self.screen.lines

            for k in range(self._rows):
                idx = start + k
                buf_y = None
                if k < len(hist_rows):
                    row = hist_rows[k]
                else:
                    buf_y = idx - nb_top
                    row = buffer[buf_y] if 0 <= buf_y < lines else None
                if row is None:
                    view_texts.append(None)
                    continue
                chars = []
                for x in range(cols):
                    cell = row[x]
                    ch_data = cell.data
                    chars.append(ch_data or " ")
                    fg = _resolve(cell.fg, _DEFAULT_FG, cell.bold)
                    bg = _resolve(cell.bg, _DEFAULT_BG)
                    is_cursor = (
                        show_cursor and buf_y is not None
                        and x == cursor.x and buf_y == cursor.y
                    )
                    if cell.reverse != is_cursor:
                        fg, bg = bg, fg
                    if sel is not None and self._in_selection(k, x, sel):
                        bg = sel_bg
                        rect = QRectF(x * cw, k * ch, cw, ch)
                        p.fillRect(rect, bg)
                    elif bg != default_bg:
                        p.fillRect(QRectF(x * cw, k * ch, cw, ch), bg)
                    if ch_data and ch_data != " ":
                        p.setPen(fg)
                        p.drawText(x * cw, k * ch + ascent, ch_data)
                view_texts.append("".join(chars))
        # 선택복사용 스냅샷(텍스트) — 락 밖에서도 안전
        self._view_rows = view_texts
        p.end()

    # -------------------------------------------------------------- 선택
    def _cell_at(self, pos) -> Cell:
        col = int(pos.x() // self._cw)
        row = int(pos.y() // self._ch)
        col = max(0, min(self.screen.columns - 1, col))
        row = max(0, min(self._rows - 1, row))
        return (row, col)

    def _ordered_selection(self) -> Optional[Tuple[Cell, Cell]]:
        if self._sel_start is None or self._sel_end is None:
            return None
        a, b = self._sel_start, self._sel_end
        return (a, b) if a <= b else (b, a)

    @staticmethod
    def _in_selection(row: int, col: int, sel: Tuple[Cell, Cell]) -> bool:
        (r1, c1), (r2, c2) = sel
        return (r1, c1) <= (row, col) <= (r2, c2)

    def _clear_selection(self) -> None:
        self._sel_start = self._sel_end = None
        self._selecting = False

    def _selected_text(self) -> str:
        # _view_rows 는 paintEvent 에서 만든 텍스트 스냅샷(락 불필요)
        sel = self._ordered_selection()
        if sel is None:
            return ""
        (r1, c1), (r2, c2) = sel
        lines = []
        for r in range(r1, r2 + 1):
            if r < 0 or r >= len(self._view_rows):
                continue
            rowtext = self._view_rows[r]
            if not rowtext:
                lines.append("")
                continue
            sc = c1 if r == r1 else 0
            ec = c2 if r == r2 else len(rowtext) - 1
            lines.append(rowtext[sc:ec + 1].rstrip())
        return "\n".join(lines)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setFocus()
            self._sel_start = self._sel_end = self._cell_at(event.position())
            self._selecting = True
            self.update()
        elif event.button() == Qt.MiddleButton:
            self._paste_primary()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            self._sel_end = self._cell_at(event.position())
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            self._sel_end = self._cell_at(event.position())
            if self._sel_start == self._sel_end:
                self._clear_selection()
            else:
                text = self._selected_text()
                if text:  # 선택 즉시 PRIMARY 클립보드에 복사(X11 관례)
                    cb = QApplication.clipboard()
                    if cb.supportsSelection():
                        cb.setText(text, QClipboard.Selection)
            self.update()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        act_copy = menu.addAction("복사")
        act_copy.setEnabled(self._ordered_selection() is not None)
        act_paste = menu.addAction("붙여넣기")
        menu.addSeparator()
        act_save = menu.addAction("전체 내용 저장... (현재 스크롤백)")
        if self._log_path is None:
            act_log = menu.addAction("세션 로그 시작... (이후 전체 기록)")
        else:
            act_log = menu.addAction("세션 로그 중지")
        chosen = menu.exec(event.globalPos())
        if chosen == act_copy:
            self._copy()
        elif chosen == act_paste:
            self._paste()
        elif chosen == act_save:
            self.save_all_to_file()
        elif chosen == act_log:
            if self._log_path is None:
                self.start_session_log()
            else:
                self.stop_session_log()

    # ------------------------------------------------------- 세션 로그
    def is_logging(self) -> bool:
        return self._log_path is not None

    def start_session_log(self) -> None:
        host = self.client.info.host if (self.client and self.client.info) else "terminal"
        path, _ = QFileDialog.getSaveFileName(
            self, "세션 로그 저장 시작", f"{host}-session.log",
            "로그/텍스트 (*.log *.txt);;모든 파일 (*)",
        )
        if not path:
            return
        try:
            fh = open(path, "w", encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "실패", str(exc))
            return
        log = _SessionLog(fh)
        existing = self.get_all_text()  # 현재까지의 스크롤백 먼저 기록
        if existing:
            log.write_raw(existing)
        old = self._reader.set_log(log)  # 이후 출력은 리더 스레드에서 기록
        if old is not None:
            old.close()
        self._log_path = path
        QMessageBox.information(
            self, "세션 로그 시작",
            f"이후 모든 출력이 저장됩니다:\n{path}\n\n중지: 우클릭 → '세션 로그 중지'",
        )

    def stop_session_log(self) -> None:
        if self._log_path is None:
            return
        old = self._reader.set_log(None)
        if old is not None:
            old.close()
        path, self._log_path = self._log_path, None
        QMessageBox.information(self, "세션 로그 중지", f"저장 완료:\n{path}")

    # ------------------------------------------------------- 전체 내용 저장
    def _row_text(self, row) -> str:
        cols = self.screen.columns
        return "".join((row[x].data or " ") for x in range(cols)).rstrip()

    def get_all_text(self) -> str:
        """스크롤백(히스토리) + 현재 화면 전체 텍스트."""
        with self._lock:
            lines = [self._row_text(r) for r in list(self.screen.history.top)]
            buf = self.screen.buffer
            for y in range(self.screen.lines):
                lines.append(self._row_text(buf[y]))
        while lines and not lines[-1].strip():  # 끝의 빈 줄 제거
            lines.pop()
        return ("\n".join(lines) + "\n") if lines else ""

    def save_all_to_file(self) -> None:
        text = self.get_all_text()
        if not text.strip():
            QMessageBox.information(self, "안내", "저장할 내용이 없습니다.")
            return
        host = self.client.info.host if (self.client and self.client.info) else "terminal"
        default = f"{host}.log"
        path, _ = QFileDialog.getSaveFileName(
            self, "터미널 내용 저장", default,
            "로그/텍스트 (*.log *.txt);;모든 파일 (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as exc:
            QMessageBox.critical(self, "저장 실패", str(exc))
            return
        QMessageBox.information(self, "저장 완료", f"터미널 내용을 저장했습니다.\n{path}")

    def _copy(self) -> None:
        text = self._selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def _paste(self) -> None:
        self._send_paste(QApplication.clipboard().text())

    def _paste_primary(self) -> None:
        cb = QApplication.clipboard()
        text = cb.text(QClipboard.Selection) if cb.supportsSelection() else cb.text()
        self._send_paste(text)

    def _bracketed_paste(self) -> bool:
        """실행 중인 프로그램(bash/zsh/vim 등)이 브래킷 붙여넣기를 켰는지."""
        try:
            with self._lock:
                return _BRACKETED_PASTE in self.screen.mode
        except Exception:
            return False

    def _send_paste(self, text: str) -> None:
        if not self._alive or not text:
            return
        text = sanitize_paste(text)
        if not text:
            return
        if self._bracketed_paste():
            # 셸이 '붙여넣은 텍스트'로 인식 → 줄바꿈이 있어도 Enter 전까지 실행하지 않는다
            payload = _PASTE_START + text.replace("\n", "\r") + _PASTE_END
        else:
            # 브래킷 모드가 없는 셸(구형 ash 등)은 줄바꿈마다 즉시 실행하므로 먼저 확인
            if "\n" in text and not self._confirm_multiline_paste(text):
                return
            payload = text.replace("\n", "\r")
        self._scroll_to_bottom()
        self._writer.write(payload.encode("utf-8"))

    def _confirm_multiline_paste(self, text: str) -> bool:
        lines = text.split("\n")
        preview = "\n".join(ln[:120] for ln in lines[:12])
        if len(lines) > 12:
            preview += f"\n… (총 {len(lines)}줄)"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("여러 줄 붙여넣기")
        box.setText(
            f"줄바꿈이 포함된 {len(lines)}줄을 붙여넣습니다.\n"
            "이 셸에서는 줄마다 바로 실행될 수 있습니다. 계속할까요?"
        )
        box.setDetailedText(text[:20000])
        box.setInformativeText(preview)
        yes = box.addButton("붙여넣기", QMessageBox.AcceptRole)
        no = box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(no)
        box.setEscapeButton(no)
        box.exec()
        return box.clickedButton() is yes

    # -------------------------------------------------------------- 입력
    # 방향/편집 키 (수정자 포함 시 xterm CSI 인코딩)
    _CURSOR = {
        Qt.Key_Up: "A", Qt.Key_Down: "B", Qt.Key_Right: "C", Qt.Key_Left: "D",
        Qt.Key_Home: "H", Qt.Key_End: "F",
    }
    _TILDE = {
        Qt.Key_Insert: "2", Qt.Key_Delete: "3",
        Qt.Key_PageUp: "5", Qt.Key_PageDown: "6",
    }
    _FKEY_SS3 = {Qt.Key_F1: "P", Qt.Key_F2: "Q", Qt.Key_F3: "R", Qt.Key_F4: "S"}
    _FKEY_NUM = {
        Qt.Key_F5: "15", Qt.Key_F6: "17", Qt.Key_F7: "18", Qt.Key_F8: "19",
        Qt.Key_F9: "20", Qt.Key_F10: "21", Qt.Key_F11: "23", Qt.Key_F12: "24",
    }
    # Ctrl+기호 → 제어문자
    _CTRL_SYM = {
        Qt.Key_BracketLeft: 0x1b, Qt.Key_BracketRight: 0x1d,
        Qt.Key_Backslash: 0x1c, Qt.Key_AsciiCircum: 0x1e,
        Qt.Key_Underscore: 0x1f, Qt.Key_Space: 0x00,
    }

    def is_alive(self) -> bool:
        return self._alive

    def send_text(self, text: str) -> None:
        """외부(배치 실행 등)에서 터미널로 텍스트를 입력."""
        if not self._alive or not text:
            return
        self._scroll_to_bottom()
        self._writer.write(text.encode("utf-8"))

    def keyPressEvent(self, event) -> None:
        if not self._alive:
            return
        mod = event.modifiers()
        key = event.key()
        # Shift+PageUp / PageDown : 스크롤백 이동 (셸로 전송하지 않음)
        if mod & Qt.ShiftModifier and key in (Qt.Key_PageUp, Qt.Key_PageDown):
            delta = -self._rows if key == Qt.Key_PageUp else self._rows
            self._vbar.setValue(self._vbar.value() + delta)
            return
        # macOS: Cmd+C (복사) / Cmd+V (붙여넣기)
        if (mod & Qt.MetaModifier) and not (mod & (Qt.ControlModifier | Qt.AltModifier)):
            if key == Qt.Key_C:
                self._copy()
                return
            if key == Qt.Key_V:
                self._paste()
                return
        # Ctrl+Shift+C/V : 복사 / 붙여넣기
        if (mod & Qt.ControlModifier) and (mod & Qt.ShiftModifier):
            if key == Qt.Key_C:
                self._copy()
                return
            if key == Qt.Key_V:
                self._paste()
                return
        # Ctrl+Insert : 복사 / Shift+Insert : 붙여넣기
        if key == Qt.Key_Insert:
            if mod & Qt.ControlModifier:
                self._copy()
                return
            if mod & Qt.ShiftModifier:
                self._paste()
                return
        data = self._map_key(event)
        if data:
            self._scroll_to_bottom()  # 입력 시 바닥으로
            self._writer.write(data)

    def inputMethodEvent(self, event) -> None:
        """IME 조합 확정 문자열(예: 한글)을 셸로 전송."""
        text = event.commitString()
        if self._alive and text:
            self._scroll_to_bottom()
            self._writer.write(text.encode("utf-8"))
        event.accept()

    @staticmethod
    def _xterm_mod(mod) -> int:
        """xterm 수정자 파라미터: 1 + Shift(1)+Alt(2)+Ctrl(4)."""
        code = 1
        if mod & Qt.ShiftModifier:
            code += 1
        if mod & Qt.AltModifier:
            code += 2
        if mod & Qt.ControlModifier:
            code += 4
        return code

    @staticmethod
    def _meta(data: bytes, mod) -> bytes:
        """Alt(메타) 조합이면 ESC 접두."""
        return (b"\x1b" + data) if (mod & Qt.AltModifier) else data

    def _app_cursor_keys(self) -> bool:
        """vim 등이 켜는 애플리케이션 커서 키 모드(DECCKM) 여부."""
        try:
            with self._lock:
                return _DECCKM in self.screen.mode
        except Exception:
            return False

    def _map_key(self, event) -> bytes:
        key = event.key()
        mod = event.modifiers()
        m = self._xterm_mod(mod)

        # 방향/편집 키 (수정자는 CSI 파라미터로 인코딩)
        if key in self._CURSOR:
            letter = self._CURSOR[key]
            if m == 1:
                # 애플리케이션 커서 키 모드(vim 등)면 SS3(\x1bO), 아니면 CSI(\x1b[)
                prefix = "\x1bO" if self._app_cursor_keys() else "\x1b["
                return (prefix + letter).encode()
            return ("\x1b[1;%d%s" % (m, letter)).encode()
        if key in self._TILDE:
            num = self._TILDE[key]
            return (("\x1b[%s~" % num) if m == 1
                    else ("\x1b[%s;%d~" % (num, m))).encode()
        if key in self._FKEY_SS3:
            l = self._FKEY_SS3[key]
            return (("\x1bO" + l) if m == 1
                    else ("\x1b[1;%d%s" % (m, l))).encode()
        if key in self._FKEY_NUM:
            num = self._FKEY_NUM[key]
            return (("\x1b[%s~" % num) if m == 1
                    else ("\x1b[%s;%d~" % (num, m))).encode()

        # 기본 편집 키 (Alt 조합 시 ESC 접두)
        if key in (Qt.Key_Return, Qt.Key_Enter):
            return self._meta(b"\r", mod)
        if key == Qt.Key_Backtab:
            return b"\x1b[Z"
        if key == Qt.Key_Tab:
            return self._meta(b"\t", mod)
        if key == Qt.Key_Escape:
            return self._meta(b"\x1b", mod)
        if key == Qt.Key_Backspace:
            base = b"\x08" if (mod & Qt.ControlModifier) else b"\x7f"
            return (b"\x1b" + base) if (mod & Qt.AltModifier) else base

        # Ctrl 조합 (문자/기호 → 제어문자, Alt 동반 시 ESC 접두)
        if mod & Qt.ControlModifier:
            if Qt.Key_A <= key <= Qt.Key_Z:
                return self._meta(bytes([key - Qt.Key_A + 1]), mod)
            if key in self._CTRL_SYM:
                return self._meta(bytes([self._CTRL_SYM[key]]), mod)

        # Alt(메타) + 일반 문자 → ESC + 문자 (AltGr=Ctrl+Alt 는 제외하고 텍스트로 처리)
        text = event.text()
        if (mod & Qt.AltModifier) and not (mod & Qt.ControlModifier):
            ch = text
            if not ch:
                if Qt.Key_A <= key <= Qt.Key_Z:
                    ch = chr(key).lower()
                elif Qt.Key_0 <= key <= Qt.Key_9:
                    ch = chr(key)
            if ch:
                return b"\x1b" + ch.encode("utf-8")

        if text:
            return text.encode("utf-8")
        return b""

    def focusNextPrevChild(self, next_child: bool) -> bool:
        # Tab/Shift+Tab 을 포커스 이동에 쓰지 않고 셸(자동완성)로 전달
        return False

    def focusInEvent(self, event) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)

    def sizeHint(self):  # noqa: D401
        from PySide6.QtCore import QSize
        return QSize(int(80 * self._cw) + self._sbw, int(24 * self._ch))

    # ------------------------------------------------------------ 정리
    def shutdown(self) -> None:
        self._alive = False
        self._log_path = None
        self._flush_timer.stop()
        self._writer.stop()
        self._reader.stop()       # run() 종료 시 세션 로그도 닫힘
        # 채널을 먼저 닫아 recv 를 즉시 깨운다 → 아래 wait 가 거의 바로 끝난다
        try:
            self.channel.close()
        except Exception:
            pass
        client = self.client  # 참조는 유지(재연결 시 접속 정보 사용)
        if client is not None:
            # transport 종료는 내부 스레드 join 을 포함하므로 UI 스레드 밖에서 수행
            threading.Thread(
                target=client.close, daemon=True, name="bt-ssh-close"
            ).start()
        reader = self._reader
        if not reader.wait(500):
            # 대량 출력 파싱 중이면 조금 더 걸릴 수 있다. 끝날 때까지 참조만 유지.
            _ORPHAN_READERS.add(reader)
            reader.finished.connect(lambda r=reader: _ORPHAN_READERS.discard(r))
