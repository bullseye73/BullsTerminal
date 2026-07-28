"""메인 윈도우: 좌측 명령 패널 + 우측 터미널 탭들.

각 터미널 탭은 자신의 SSH 연결을 가지며, 탭마다 다른 호스트(IP)로 연결할 수 있다.
배치 실행(선택/그룹/더블클릭)은 현재 활성 터미널 탭에 명령을 보내 실행한다.
"""
from __future__ import annotations

import re
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QFontDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import store
from core.models import Command, Group
from ssh.client import ConnectionInfo, SSHClient
from ui.bash_highlighter import BashHighlighter
from ui.command_editor import CommandEditor
from ui.connect_dialog import ConnectDialog
from ui.terminal_widget import TerminalWidget


# 명령의 첫 토큰: sudo/doas 접두 + 명령이름/경로/변수 형태
_CMD_START_RE = re.compile(
    r"^(?:sudo\s+|doas\s+)?"
    r"(?:[A-Za-z_][\w.+-]*|\.{0,2}/\S+|~/?\S*|\$\{?\w+)"
)
_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://")
# 제어문자(탭/개행 제외)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def looks_like_command(text: str) -> bool:
    """클립보드 텍스트가 셸에서 쓸 만한 명령처럼 보이는지 판단(휴리스틱)."""
    t = text.strip()
    if not t or len(t) > 4000:
        return False
    if _CTRL_RE.search(t):
        return False
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if not lines:
        return False
    first = lines[0].strip()
    if _URL_RE.match(first):  # 순수 URL 제외
        return False
    # 첫 줄이 명령/경로/변수 형태로 시작해야 함(한글 등으로 시작하는 문장 제외)
    return bool(_CMD_START_RE.match(first))


class CommandEdit(QPlainTextEdit):
    """여러 줄 명령 입력창. Ctrl+Enter 로 전송 요청."""

    send_requested = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (
            event.modifiers() & Qt.ControlModifier
        ):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class _ConnectWorker(QThread):
    """백그라운드에서 SSH 연결 + 셸 채널 오픈 (GUI 프리징 방지)."""

    ok = Signal(object, object)  # (SSHClient, channel)
    fail = Signal(str)

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__()
        self._info = info

    def run(self) -> None:
        client = SSHClient()
        try:
            client.connect(self._info)
            channel = client.open_shell()
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            self.fail.emit(f"{type(exc).__name__}: {exc}")
            return
        self.ok.emit(client, channel)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.groups: List[Group] = store.load_groups()
        self._sort_data()
        self._term_counter = 0
        self._syncing = False  # 전체선택 체크박스 동기화 중 재귀 방지
        self._last_info: Optional[ConnectionInfo] = None  # 새 터미널 다이얼로그 프리필
        self._clip_history: List[str] = []  # 클립보드 기록(최신순, 세션 메모리)
        self._connecting = False              # 연결 진행 중 여부
        self._conn_worker: Optional[_ConnectWorker] = None  # 현재 연결 워커
        self._conn_workers: set = set()       # 실행 중 워커 참조(GC 방지)
        self._conn_dialog: Optional[QProgressDialog] = None

        # 터미널/입력창 공용 폰트 (설정 저장/복원)
        s = store.load_settings()
        self._term_font = QFont(s["font_family"], s["font_size"])
        self._term_font.setStyleHint(QFont.Monospace)

        self.setWindowTitle("rsCommand — SSH 일괄 명령 실행")
        self.resize(1180, 760)

        self._build_ui()
        self._refresh_groups()
        self._update_connection_label()

    # ---------------------------------------------------------------- UI 구성
    def _build_ui(self) -> None:
        style = self.style()
        icon_new = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        icon_reload = style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        icon_close = style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        icon_font = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)

        # ---- 메뉴바 ----
        conn_menu = self.menuBar().addMenu("연결")
        act_new_term = conn_menu.addAction(icon_new, "새 터미널")
        conn_menu.addSeparator()
        act_reconnect = conn_menu.addAction(icon_reload, "재연결 (활성 탭)")
        act_disconnect = conn_menu.addAction(icon_close, "연결끊기 (활성 탭)")
        act_new_term.triggered.connect(self._on_new_terminal)
        act_reconnect.triggered.connect(self._on_reconnect)
        act_disconnect.triggered.connect(self._on_disconnect)

        settings_menu = self.menuBar().addMenu("설정")
        act_font = settings_menu.addAction(icon_font, "글꼴·크기 변경...")
        act_font.triggered.connect(self._on_change_font)

        cmd_menu = self.menuBar().addMenu("명령 관리")
        act_export = cmd_menu.addAction("명령 백업 (내보내기)...")
        act_import = cmd_menu.addAction("명령 복원 (가져오기)...")
        act_export.triggered.connect(self._on_export_commands)
        act_import.triggered.connect(self._on_import_commands)

        # ---- 상단 상태바 (아이콘 버튼) ----
        self.conn_label = QLabel()

        def _icon_btn(icon, tip, slot):
            b = QPushButton()
            b.setIcon(icon)
            b.setToolTip(tip)
            b.setFlat(True)
            b.setFixedWidth(34)
            b.clicked.connect(slot)
            return b

        self.font_btn = _icon_btn(icon_font, "글꼴·크기 변경", self._on_change_font)
        self.reconnect_btn = _icon_btn(icon_reload, "재연결 (활성 탭)", self._on_reconnect)
        self.disconnect_btn = _icon_btn(icon_close, "연결끊기 (활성 탭)", self._on_disconnect)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.conn_label, 1)
        top_bar.addWidget(self.font_btn)
        top_bar.addWidget(self.reconnect_btn)
        top_bar.addWidget(self.disconnect_btn)

        # ---- 좌측: 명령 패널 (그룹 + 명령 + 실행 버튼) ----
        list_style = "QListWidget::item { padding: 5px 4px; }"

        self.group_list = QListWidget()
        self.group_list.setStyleSheet(list_style)
        self.group_list.currentRowChanged.connect(self._on_group_changed)
        g_add = QPushButton("＋")
        g_ren = QPushButton("이름")
        g_del = QPushButton("삭제")
        g_add.setToolTip("그룹 추가")
        g_ren.setToolTip("그룹 이름변경")
        g_del.setToolTip("그룹 삭제")
        for b in (g_add, g_ren, g_del):
            b.setMaximumWidth(56)
        g_add.clicked.connect(self._on_group_add)
        g_ren.clicked.connect(self._on_group_rename)
        g_del.clicked.connect(self._on_group_delete)

        group_header = QHBoxLayout()
        group_header.addWidget(QLabel("기능 그룹"))
        group_header.addStretch(1)
        for b in (g_add, g_ren, g_del):
            group_header.addWidget(b)

        group_box = QWidget()
        group_layout = QVBoxLayout(group_box)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.addLayout(group_header)
        group_layout.addWidget(self.group_list, 1)

        self.command_list = QListWidget()
        self.command_list.setStyleSheet(list_style)
        self.command_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.command_list.itemDoubleClicked.connect(self._on_command_run_one)
        self.command_list.itemChanged.connect(self._on_item_changed)
        self.command_list.currentItemChanged.connect(self._on_command_selected)
        self.command_list.setToolTip("클릭: 아래 입력창에 표시 / 더블클릭: 바로 실행 / 체크: 선택 실행")

        self.select_all_check = QCheckBox("전체")
        self.select_all_check.setTristate(True)
        self.select_all_check.clicked.connect(self._on_select_all_clicked)

        c_add = QPushButton("＋")
        c_edit = QPushButton("수정")
        c_del = QPushButton("삭제")
        c_add.setToolTip("명령 추가")
        for b in (c_add, c_edit, c_del):
            b.setMaximumWidth(56)
        c_add.clicked.connect(self._on_command_add)
        c_edit.clicked.connect(self._on_command_edit)
        c_del.clicked.connect(self._on_command_delete)

        self.run_selected_btn = QPushButton("▶ 선택")
        self.run_group_btn = QPushButton("▶▶ 그룹")
        self.run_selected_btn.setToolTip("체크한 명령들을 순차 실행")
        self.run_group_btn.setToolTip("그룹의 모든 명령을 순차 실행")
        self.run_selected_btn.clicked.connect(self._on_run_selected)
        self.run_group_btn.clicked.connect(self._on_run_group)

        # 명령 목록 헤더: 전체선택 체크 + CRUD 버튼
        header_row = QHBoxLayout()
        header_row.addWidget(self.select_all_check)
        header_row.addStretch(1)
        for b in (c_add, c_edit, c_del):
            header_row.addWidget(b)

        run_btns = QHBoxLayout()
        run_btns.addWidget(self.run_selected_btn)
        run_btns.addWidget(self.run_group_btn)

        command_box = QWidget()
        command_layout = QVBoxLayout(command_box)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.addWidget(QLabel("명령"))
        command_layout.addLayout(header_row)
        command_layout.addWidget(self.command_list, 1)
        command_layout.addLayout(run_btns)

        left_split = QSplitter(Qt.Vertical)
        left_split.addWidget(group_box)
        left_split.addWidget(command_box)
        left_split.setStretchFactor(0, 1)
        left_split.setStretchFactor(1, 2)
        left_split.setHandleWidth(8)
        left_split.setChildrenCollapsible(False)
        left_split.setStyleSheet(
            "QSplitter::handle { background: #c0c0c0; margin: 2px 0; border-radius: 2px; }"
        )

        # ---- 우측: 터미널 탭 ----
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tabs.currentChanged.connect(lambda _i: self._update_connection_label())

        new_term_btn = QPushButton(" 터미널")
        new_term_btn.setIcon(icon_new)
        new_term_btn.setToolTip("새 터미널 (다른 호스트로도 연결 가능)")
        new_term_btn.clicked.connect(self._on_new_terminal)
        self.tabs.setCornerWidget(new_term_btn)

        # 터미널 하단 명령 입력 패널 (여러 줄 편집 + 높이 가변)
        self.cmd_edit = CommandEdit()
        self.cmd_edit.setPlaceholderText(
            "명령을 클릭하면 여기 표시됩니다. 수정 후 Ctrl+Enter 또는 [입력]으로 실행 "
            "(여러 줄 입력 가능)"
        )
        self.cmd_edit.setFont(self._term_font)
        # 터미널과 어울리는 다크 배경 + bash 구문 강조
        self.cmd_edit.setStyleSheet(
            "QPlainTextEdit { background:#1e1e1e; color:#d3d7cf;"
            " selection-background-color:#44475a; }"
        )
        _pal = self.cmd_edit.palette()
        _pal.setColor(QPalette.PlaceholderText, QColor("#7f8c8d"))
        self.cmd_edit.setPalette(_pal)
        self._cmd_highlighter = BashHighlighter(self.cmd_edit.document())
        save_btn = QPushButton("저장")
        save_btn.setToolTip("수정한 내용을 선택된 명령에 저장")
        save_btn.clicked.connect(self._on_save_cmd)
        send_btn = QPushButton("입력")
        send_btn.setToolTip("현재 터미널로 전송 (Ctrl+Enter)")
        send_btn.clicked.connect(self._on_send_cmd)
        self.cmd_edit.send_requested.connect(self._on_send_cmd)

        cmd_header = QHBoxLayout()
        cmd_header.addWidget(QLabel("명령 입력 (Ctrl+Enter 전송)"))
        cmd_header.addStretch(1)
        cmd_header.addWidget(save_btn)
        cmd_header.addWidget(send_btn)

        cmd_panel = QWidget()
        cmd_layout = QVBoxLayout(cmd_panel)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.addLayout(cmd_header)
        cmd_layout.addWidget(self.cmd_edit, 1)

        # 터미널 ↔ 명령 입력 패널: 세로 스플리터로 높이 조절
        right_split = QSplitter(Qt.Vertical)
        right_split.addWidget(self.tabs)
        right_split.addWidget(cmd_panel)
        right_split.setStretchFactor(0, 1)
        right_split.setStretchFactor(1, 0)
        right_split.setSizes([620, 120])
        right_split.setHandleWidth(8)
        right_split.setStyleSheet(
            "QSplitter::handle { background: #c0c0c0; margin: 2px 0; border-radius: 2px; }"
        )

        central_split = QSplitter(Qt.Horizontal)
        left_wrap = QWidget()
        left_wrap_layout = QVBoxLayout(left_wrap)
        left_wrap_layout.setContentsMargins(0, 0, 0, 0)
        left_wrap_layout.addWidget(left_split)
        left_wrap.setMinimumWidth(180)
        left_wrap.setMaximumWidth(320)
        central_split.addWidget(left_wrap)
        central_split.addWidget(right_split)
        central_split.setStretchFactor(0, 0)
        central_split.setStretchFactor(1, 1)
        central_split.setSizes([240, 940])
        central_split.setHandleWidth(6)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.addLayout(top_bar)
        central_layout.addWidget(central_split, 1)
        self.setCentralWidget(central)

        # ---- 클립보드 기록 도킹 패널 (우측/하단 도킹 + 분리 가능) ----
        self.clip_list = QListWidget()
        self.clip_list.setStyleSheet("QListWidget::item { padding: 4px 4px; }")
        self.clip_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.clip_list.itemSelectionChanged.connect(self._on_clip_selection_changed)
        self.clip_list.itemDoubleClicked.connect(self._on_clip_run)

        clip_del = QPushButton("삭제")
        clip_clear = QPushButton("전체 삭제")
        clip_del.setToolTip("선택 항목 삭제")
        clip_clear.setToolTip("기록 및 시스템 클립보드 비우기")
        clip_del.clicked.connect(self._on_clip_delete)
        clip_clear.clicked.connect(self._on_clip_clear)
        clip_btns = QHBoxLayout()
        clip_btns.addWidget(clip_del)
        clip_btns.addWidget(clip_clear)
        clip_btns.addStretch(1)

        clip_box = QWidget()
        clip_layout = QVBoxLayout(clip_box)
        clip_layout.setContentsMargins(4, 4, 4, 4)
        clip_layout.addWidget(QLabel("클릭 → 입력창 / 더블클릭 → 실행"))
        clip_layout.addWidget(self.clip_list, 1)
        clip_layout.addLayout(clip_btns)

        self.clip_dock = QDockWidget("클립보드 기록", self)
        self.clip_dock.setObjectName("clipboardDock")
        self.clip_dock.setWidget(clip_box)
        self.clip_dock.setAllowedAreas(
            Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea | Qt.LeftDockWidgetArea
        )
        self.clip_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.clip_dock)

        view_menu = self.menuBar().addMenu("보기")
        view_menu.addAction(self.clip_dock.toggleViewAction())

        # 시스템 클립보드 감시 + 현재 내용 시드
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        self._on_clipboard_changed()

    # ---------------------------------------------------- 클립보드 기록
    def _on_clipboard_changed(self) -> None:
        text = QApplication.clipboard().text()
        if not text or not text.strip():
            return
        text = text.replace("\r\n", "\n").rstrip("\n")
        if not looks_like_command(text):  # 셸 명령처럼 보이는 것만 저장
            return
        if text in self._clip_history:
            self._clip_history.remove(text)
        self._clip_history.insert(0, text)
        del self._clip_history[100:]  # 최대 100개
        self._refresh_clip_list()

    def _refresh_clip_list(self) -> None:
        self.clip_list.blockSignals(True)
        self.clip_list.clear()
        for t in self._clip_history:
            first = t.strip().splitlines()[0] if t.strip() else ""
            if len(first) > 80:
                first = first[:80] + "…"
            item = QListWidgetItem(first)
            item.setToolTip(t)
            self.clip_list.addItem(item)
        self.clip_list.blockSignals(False)

    def _selected_clip_rows(self) -> List[int]:
        return sorted(self.clip_list.row(it) for it in self.clip_list.selectedItems())

    def _on_clip_selection_changed(self) -> None:
        rows = self._selected_clip_rows()
        texts = [self._clip_history[r] for r in rows if 0 <= r < len(self._clip_history)]
        if texts:
            # 여러 개 선택 시 줄바꿈으로 이어 입력창에 표시(줄마다 실행 가능)
            self.cmd_edit.setPlainText("\n".join(texts))

    def _on_clip_run(self, item: QListWidgetItem) -> None:
        row = self.clip_list.row(item)
        if 0 <= row < len(self._clip_history):
            self.cmd_edit.setPlainText(self._clip_history[row])
            self._on_send_cmd()

    def _on_clip_delete(self) -> None:
        rows = self._selected_clip_rows()
        if not rows:
            return
        for r in sorted(rows, reverse=True):  # 뒤에서부터 삭제(인덱스 보존)
            if 0 <= r < len(self._clip_history):
                del self._clip_history[r]
        self._refresh_clip_list()

    def _on_clip_clear(self) -> None:
        if not self._clip_history:
            QApplication.clipboard().clear()
            return
        if QMessageBox.question(
            self, "전체 삭제", "클립보드 기록과 시스템 클립보드를 비울까요?"
        ) != QMessageBox.Yes:
            return
        self._clip_history.clear()
        self._refresh_clip_list()
        QApplication.clipboard().clear()

    # ------------------------------------------------------------- 상태 갱신
    def _current_terminal(self) -> Optional[TerminalWidget]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, TerminalWidget) else None

    def _update_connection_label(self) -> None:
        term = self._current_terminal()
        if term is not None and term.is_alive() and term.client and term.client.info:
            info = term.client.info
            self.conn_label.setText(f"● 연결됨: {info.username}@{info.host}:{info.port}")
            self.conn_label.setStyleSheet("color: #22c55e; font-weight: bold;")
        else:
            self.conn_label.setText("● 연결된 터미널 없음")
            self.conn_label.setStyleSheet("color: #ef4444; font-weight: bold;")

    def _current_group(self) -> Optional[Group]:
        row = self.group_list.currentRow()
        if 0 <= row < len(self.groups):
            return self.groups[row]
        return None

    def _refresh_groups(self, keep_row: Optional[int] = None) -> None:
        row = self.group_list.currentRow() if keep_row is None else keep_row
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for g in self.groups:
            self.group_list.addItem(f"{g.name}  ({len(g.commands)})")
        self.group_list.blockSignals(False)
        if self.groups:
            if row is None or row < 0 or row >= len(self.groups):
                row = 0
            self.group_list.setCurrentRow(row)
        self._refresh_commands()

    def _refresh_commands(self) -> None:
        self._syncing = True
        self.command_list.clear()
        group = self._current_group()
        if group is not None:
            for cmd in group.commands:
                item = QListWidgetItem(self._command_display(cmd))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                tip = cmd.command
                if cmd.description:
                    tip += f"\n\n{cmd.description}"
                item.setToolTip(tip)
                self.command_list.addItem(item)
        self._syncing = False
        self._sync_select_all()

    @staticmethod
    def _command_display(cmd: Command) -> str:
        # 제목(라벨)만 표시. 전체 명령/설명은 툴팁으로 확인.
        return cmd.label

    # ------------------------------------------------------------ 그룹 편집
    def _on_group_changed(self, _row: int) -> None:
        self._refresh_commands()

    def _sort_data(self) -> None:
        """그룹은 이름으로, 각 그룹의 명령은 라벨로 정렬(대소문자 무시)."""
        self.groups.sort(key=lambda g: g.name.casefold())
        for g in self.groups:
            g.commands.sort(key=lambda c: c.label.casefold())

    def _select_group(self, group: Group) -> None:
        for i, g in enumerate(self.groups):
            if g is group:
                self.group_list.setCurrentRow(i)
                return

    def _select_command(self, cmd: Command) -> None:
        group = self._current_group()
        if group is None:
            return
        for i, c in enumerate(group.commands):
            if c is cmd:
                self.command_list.setCurrentRow(i)
                return

    # ------------------------------------------------------- 백업 / 복원
    def _on_export_commands(self) -> None:
        """명령 그룹 전체를 파일로 백업."""
        path, _ = QFileDialog.getSaveFileName(
            self, "명령 백업 저장", "rscommand-commands.yaml",
            "YAML 파일 (*.yaml *.yml);;모든 파일 (*)",
        )
        if not path:
            return
        try:
            store.export_groups(self.groups, path)
        except Exception as exc:
            QMessageBox.critical(self, "백업 실패", str(exc))
            return
        total = sum(len(g.commands) for g in self.groups)
        QMessageBox.information(
            self, "백업 완료",
            f"그룹 {len(self.groups)}개 / 명령 {total}개를 저장했습니다.\n{path}",
        )

    def _on_import_commands(self) -> None:
        """백업 파일에서 명령 그룹을 가져온다(병합 또는 교체)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "명령 복원 파일 선택", "",
            "YAML 파일 (*.yaml *.yml);;모든 파일 (*)",
        )
        if not path:
            return
        try:
            imported = store.import_groups(path)
        except Exception as exc:
            QMessageBox.critical(self, "복원 실패", f"파일을 읽을 수 없습니다.\n{exc}")
            return
        if not imported:
            QMessageBox.information(self, "안내", "가져올 그룹이 없습니다.")
            return

        box = QMessageBox(self)
        box.setWindowTitle("명령 복원")
        box.setIcon(QMessageBox.Question)
        box.setText(
            f"{len(imported)}개 그룹을 가져옵니다.\n"
            "기존 명령과 어떻게 처리할까요?"
        )
        merge_btn = box.addButton("병합", QMessageBox.AcceptRole)
        replace_btn = box.addButton("교체", QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is merge_btn:
            self._merge_groups(imported)
        elif clicked is replace_btn:
            self.groups = imported
        else:
            return

        self._sort_data()
        store.save_groups(self.groups)
        self._refresh_groups(keep_row=0)
        total = sum(len(g.commands) for g in self.groups)
        QMessageBox.information(
            self, "복원 완료",
            f"현재 그룹 {len(self.groups)}개 / 명령 {total}개.",
        )

    def _merge_groups(self, imported: List[Group]) -> None:
        by_name = {g.name: g for g in self.groups}
        for ig in imported:
            existing = by_name.get(ig.name)
            if existing is None:
                self.groups.append(ig)
                by_name[ig.name] = ig
                continue
            have = {(c.label, c.command) for c in existing.commands}
            for c in ig.commands:
                key = (c.label, c.command)
                if key not in have:
                    existing.commands.append(c)
                    have.add(key)

    def _on_group_add(self) -> None:
        name, ok = QInputDialog.getText(self, "그룹 추가", "그룹 이름:")
        if ok and name.strip():
            group = Group(name=name.strip())
            self.groups.append(group)
            self._sort_data()
            store.save_groups(self.groups)
            self._refresh_groups()
            self._select_group(group)

    def _on_group_rename(self) -> None:
        group = self._current_group()
        if group is None:
            return
        name, ok = QInputDialog.getText(self, "그룹 이름변경", "새 이름:", text=group.name)
        if ok and name.strip():
            group.name = name.strip()
            self._sort_data()
            store.save_groups(self.groups)
            self._refresh_groups()
            self._select_group(group)

    def _on_group_delete(self) -> None:
        group = self._current_group()
        if group is None:
            return
        if QMessageBox.question(
            self, "그룹 삭제", f"'{group.name}' 그룹을 삭제할까요?"
        ) != QMessageBox.Yes:
            return
        self.groups.remove(group)
        store.save_groups(self.groups)
        self._refresh_groups(keep_row=0)

    # ----------------------------------------------------------- 명령 편집
    def _on_command_add(self) -> None:
        group = self._current_group()
        if group is None:
            QMessageBox.information(self, "안내", "먼저 그룹을 선택/추가하세요.")
            return
        editor = CommandEditor(self)
        if editor.exec() == CommandEditor.Accepted:
            cmd = editor.result_command()
            group.commands.append(cmd)
            self._sort_data()
            store.save_groups(self.groups)
            self._refresh_groups()
            self._select_group(group)
            self._select_command(cmd)

    def _on_command_edit(self) -> None:
        group = self._current_group()
        row = self.command_list.currentRow()
        if group is None or not (0 <= row < len(group.commands)):
            return
        editor = CommandEditor(self, command=group.commands[row])
        if editor.exec() == CommandEditor.Accepted:
            cmd = editor.result_command()
            group.commands[row] = cmd
            self._sort_data()
            store.save_groups(self.groups)
            self._refresh_groups()
            self._select_group(group)
            self._select_command(cmd)

    def _on_command_delete(self) -> None:
        group = self._current_group()
        row = self.command_list.currentRow()
        if group is None or not (0 <= row < len(group.commands)):
            return
        cmd = group.commands[row]
        if QMessageBox.question(
            self, "명령 삭제", f"'{cmd.label}' 명령을 삭제할까요?"
        ) != QMessageBox.Yes:
            return
        del group.commands[row]
        store.save_groups(self.groups)
        self._refresh_groups()
        self._select_group(group)

    # ----------------------------------------------------- 선택 체크박스
    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        self._syncing = True
        for i in range(self.command_list.count()):
            self.command_list.item(i).setCheckState(state)
        self._syncing = False
        self._sync_select_all()

    def _on_select_all_clicked(self, _checked: bool) -> None:
        total = self.command_list.count()
        checked = sum(
            1 for i in range(total)
            if self.command_list.item(i).checkState() == Qt.Checked
        )
        self._set_all_checked(not (total > 0 and checked == total))

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        if self._syncing:
            return
        self._sync_select_all()

    def _sync_select_all(self) -> None:
        total = self.command_list.count()
        checked = sum(
            1 for i in range(total)
            if self.command_list.item(i).checkState() == Qt.Checked
        )
        self.select_all_check.blockSignals(True)
        if total == 0 or checked == 0:
            self.select_all_check.setCheckState(Qt.Unchecked)
        elif checked == total:
            self.select_all_check.setCheckState(Qt.Checked)
        else:
            self.select_all_check.setCheckState(Qt.PartiallyChecked)
        self.select_all_check.blockSignals(False)

    # --------------------------------------------------------------- 배치 실행
    def _checked_commands(self) -> List[Command]:
        group = self._current_group()
        if group is None:
            return []
        result = []
        for i in range(self.command_list.count()):
            if self.command_list.item(i).checkState() == Qt.Checked:
                result.append(group.commands[i])
        return result

    def _on_run_selected(self) -> None:
        cmds = self._checked_commands()
        if not cmds:
            QMessageBox.information(self, "안내", "실행할 명령을 체크하세요.")
            return
        self._run_in_terminal(cmds)

    def _on_run_group(self) -> None:
        group = self._current_group()
        if group is None or not group.commands:
            QMessageBox.information(self, "안내", "실행할 명령이 없습니다.")
            return
        self._run_in_terminal(list(group.commands))

    def _on_command_run_one(self, item: QListWidgetItem) -> None:
        """더블클릭한 명령 하나를 즉시 실행."""
        group = self._current_group()
        row = self.command_list.row(item)
        if group is None or not (0 <= row < len(group.commands)):
            return
        self._run_in_terminal([group.commands[row]])

    def _on_command_selected(self, current, _previous) -> None:
        """목록에서 명령을 선택하면 하단 입력바에 명령어를 채운다(수정 가능)."""
        if self._syncing or current is None:
            return
        group = self._current_group()
        if group is None:
            return
        row = self.command_list.row(current)
        if 0 <= row < len(group.commands):
            self.cmd_edit.setPlainText(group.commands[row].command)

    def _on_send_cmd(self) -> None:
        """하단 입력창의 (수정된) 명령을 현재 터미널로 전송. 여러 줄이면 줄마다 실행."""
        text = self.cmd_edit.toPlainText()
        if not text.strip():
            return
        term = self._active_terminal()
        if term is None:
            return
        # 줄바꿈을 CR 로 변환(줄마다 실행), 마지막에 CR 추가
        payload = text.replace("\r\n", "\n").rstrip("\n").replace("\n", "\r") + "\r"
        term.send_text(payload)
        term.setFocus()

    def _on_save_cmd(self) -> None:
        """입력창의 수정 내용을 현재 선택된 명령에 저장."""
        group = self._current_group()
        row = self.command_list.currentRow()
        if group is None or not (0 <= row < len(group.commands)):
            QMessageBox.information(self, "안내", "저장할 명령을 목록에서 선택하세요.")
            return
        text = self.cmd_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "안내", "명령 내용이 비어 있습니다.")
            return
        cmd = group.commands[row]
        if cmd.command == text:
            self.statusBar().showMessage("변경 사항이 없습니다.", 2000)
            return
        cmd.command = text
        store.save_groups(self.groups)
        # 목록 표시는 라벨만이라 순서 불변 → 툴팁만 갱신
        item = self.command_list.item(row)
        if item is not None:
            tip = cmd.command
            if cmd.description:
                tip += f"\n\n{cmd.description}"
            item.setToolTip(tip)
        self.statusBar().showMessage(f"'{cmd.label}' 명령을 저장했습니다.", 2500)

    def _on_change_font(self) -> None:
        """터미널/입력창 폰트·크기 변경 (모든 터미널 탭에 즉시 적용, 설정 저장)."""
        res = QFontDialog.getFont(self._term_font, self, "터미널/입력창 폰트")
        # PySide6 버전에 따라 (font, ok) 또는 (ok, font) 순서가 다를 수 있음
        if isinstance(res[0], bool):
            ok, font = res
        else:
            font, ok = res
        if not ok:
            return
        font.setStyleHint(QFont.Monospace)
        self._term_font = font
        self.cmd_edit.setFont(font)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, TerminalWidget):
                w.apply_font(font)
        size = font.pointSize() if font.pointSize() > 0 else store.DEFAULT_SETTINGS["font_size"]
        store.save_settings({"font_family": font.family(), "font_size": size})

    def _run_in_terminal(self, commands: List[Command]) -> None:
        parts = [c.command.strip() for c in commands if c.command.strip()]
        if not parts:
            return

        need_confirm = [c for c in commands if c.confirm]
        if need_confirm:
            names = "\n".join(f"  • {c.label}" for c in need_confirm)
            if QMessageBox.warning(
                self,
                "실행 확인",
                f"다음 명령을 실행합니다:\n\n{names}\n\n계속할까요?",
                QMessageBox.Yes | QMessageBox.No,
            ) != QMessageBox.Yes:
                return

        term = self._active_terminal()
        if term is None:
            return

        # 하나의 입력 라인으로 순차 실행(;). 단일 라인이라 sudo 프롬프트가
        # 뒤 명령을 비밀번호로 삼키지 않고 터미널에서 직접 입력받는다.
        payload = "; ".join(parts) + "\r"
        term.send_text(payload)
        term.setFocus()

    # ------------------------------------------------------- 터미널 탭 관리
    def _add_terminal(self, info: ConnectionInfo) -> None:
        """백그라운드 스레드로 연결 → UI 프리징 없이 진행. 완료 시 콜백에서 탭 생성."""
        if self._connecting:
            QMessageBox.information(self, "안내", "이미 연결을 시도 중입니다.")
            return
        self._connecting = True

        worker = _ConnectWorker(info)
        self._conn_worker = worker
        self._conn_workers.add(worker)
        worker.ok.connect(self._on_connect_ok)
        worker.fail.connect(self._on_connect_fail)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()

        dlg = QProgressDialog(
            f"{info.username}@{info.host} 연결 중...", "취소", 0, 0, self
        )
        dlg.setWindowTitle("연결 중")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(self._on_connect_cancel)
        self._conn_dialog = dlg
        dlg.show()

    def _cleanup_worker(self, worker: "_ConnectWorker") -> None:
        self._conn_workers.discard(worker)
        worker.deleteLater()

    def _close_conn_dialog(self) -> None:
        if self._conn_dialog is not None:
            try:
                self._conn_dialog.canceled.disconnect()  # 종료 시 취소 오발 방지
            except Exception:
                pass
            self._conn_dialog.close()
            self._conn_dialog.deleteLater()
            self._conn_dialog = None

    def _on_connect_ok(self, client, channel) -> None:
        if self.sender() is not self._conn_worker:
            # 취소되었거나 지난 요청의 결과 → 폐기
            try:
                client.close()
            except Exception:
                pass
            return
        self._close_conn_dialog()
        self._connecting = False
        self._conn_worker = None

        info = client.info
        term = TerminalWidget(channel, client=client, font=self._term_font)
        term.session_closed.connect(self._on_terminal_session_closed)
        self._term_counter += 1
        title = f"{info.username}@{info.host}" if info else f"터미널 {self._term_counter}"
        index = self.tabs.addTab(term, title)
        self.tabs.setCurrentIndex(index)
        term.setFocus()
        self._last_info = info
        self._update_connection_label()

    def _on_connect_fail(self, msg: str) -> None:
        if self.sender() is not self._conn_worker:
            return  # 취소/지난 요청
        self._close_conn_dialog()
        self._connecting = False
        self._conn_worker = None
        QMessageBox.critical(self, "연결 실패", msg)

    def _on_connect_cancel(self) -> None:
        # 워커는 소켓 타임아웃 후 종료되며 결과는 폐기됨(sender != _conn_worker)
        self._conn_worker = None
        self._connecting = False
        self._close_conn_dialog()

    def _active_terminal(self) -> Optional[TerminalWidget]:
        """현재 탭이 살아있는 터미널이면 반환. 없으면 안내(연결은 비동기라 자동 생성 안 함)."""
        term = self._current_terminal()
        if term is not None and term.is_alive():
            return term
        QMessageBox.information(self, "안내", "먼저 우측 상단 '+ 터미널'로 연결하세요.")
        return None

    def _on_new_terminal(self) -> None:
        dialog = ConnectDialog(self, prefill=self._last_info)
        if dialog.exec() == ConnectDialog.Accepted:
            self._add_terminal(dialog.connection_info())

    def open_initial_terminal(self) -> None:
        """시작 시 첫 연결 다이얼로그를 띄운다."""
        self._on_new_terminal()

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if not isinstance(widget, TerminalWidget):
            return
        widget.shutdown()
        self.tabs.removeTab(index)
        widget.deleteLater()
        self._update_connection_label()

    def _on_terminal_session_closed(self, term: TerminalWidget) -> None:
        index = self.tabs.indexOf(term)
        if index >= 0:
            title = self.tabs.tabText(index)
            if not title.endswith("(종료됨)"):
                self.tabs.setTabText(index, f"{title} (종료됨)")
        if term is self._current_terminal():
            self._update_connection_label()

    def _close_all_terminals(self) -> None:
        for i in range(self.tabs.count() - 1, -1, -1):
            widget = self.tabs.widget(i)
            if isinstance(widget, TerminalWidget):
                widget.shutdown()
                self.tabs.removeTab(i)
                widget.deleteLater()

    # --------------------------------------------------------- 연결 관리
    def _on_reconnect(self) -> None:
        """활성 탭을 같은 호스트로 재연결. 없으면 새 연결 다이얼로그."""
        term = self._current_terminal()
        if term is not None and term.client and term.client.info:
            info = term.client.info
            index = self.tabs.indexOf(term)
            term.shutdown()
            self.tabs.removeTab(index)
            term.deleteLater()
            self._add_terminal(info)
        else:
            self._on_new_terminal()

    def _on_disconnect(self) -> None:
        """활성 터미널 탭을 닫고 연결을 끊는다."""
        term = self._current_terminal()
        if term is None:
            return
        index = self.tabs.indexOf(term)
        term.shutdown()
        self.tabs.removeTab(index)
        term.deleteLater()
        self._update_connection_label()

    def closeEvent(self, event) -> None:
        # 진행 중 연결 결과는 무시(late 시그널 폐기)
        self._conn_worker = None
        self._close_all_terminals()
        super().closeEvent(event)
