"""SFTP 파일 브라우저 (WinSCP 스타일).

상단: SSH 접속된 리모트 PC의 현재 위치, 하단: 로컬 PC(기본 내 문서).
- 시스템 아이콘(QFileIconProvider), 크기/수정시간 컬럼
- 우클릭 메뉴(다운로드/업로드/이름변경/새 폴더/삭제/새로고침)
- 삭제 확인 팝업, 전송 진행률(%) 표시
- 전송은 백그라운드 스레드로 수행(GUI 프리징 방지), 진행 중 취소 가능
- 원격 목록/이름변경/새 폴더/삭제도 전용 스레드(_SftpService)에서 수행:
  네트워크가 느리거나 끊겨도 UI 스레드는 막히지 않는다.
"""
from __future__ import annotations

import os
import posixpath
import queue
import stat
import sys
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QFileInfo, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFileIconProvider,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

_ROLE_NAME = Qt.UserRole
_ROLE_ISDIR = Qt.UserRole + 1


def _human_size(n: int) -> str:
    if n is None:
        return ""
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{int(f)} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{int(n)} B"


def _fmt_time(ts) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


_SFTP_TIMEOUT = 20.0  # 초. 이 시간 동안 응답이 없으면 작업을 실패 처리(무한 대기 방지)


def _open_sftp(transport):
    """타임아웃이 걸린 SFTP 클라이언트를 연다(워커 스레드 전용)."""
    sftp = transport.open_sftp_client()
    try:
        sftp.get_channel().settimeout(_SFTP_TIMEOUT)
    except Exception:
        pass
    return sftp


def is_safe_local_name(name: str) -> bool:
    """서버가 알려준 파일명을 로컬 파일명으로 그대로 써도 되는지.

    SFTP 서버는 목록에 임의의 문자열을 넣을 수 있다. '../x' 나 절대경로를 그대로
    os.path.join 하면 선택한 로컬 폴더 밖에 파일이 써지므로 경로 성분이 있으면 거부한다.
    """
    if not name or name in (".", "..") or "\x00" in name:
        return False
    if "/" in name or (os.altsep and os.altsep in name) or os.sep in name:
        return False
    if sys.platform == "win32" and ("\\" in name or ":" in name):
        return False  # 드라이브/대체 데이터 스트림 표기
    return os.path.basename(name) == name


class _TransferCancelled(Exception):
    pass


class _SftpWorker(QThread):
    """백그라운드 파일 전송 (get/put) + 진행률. cancel() 로 중단 가능."""

    progress = Signal(int, str)  # percent(0-100), filename
    done = Signal(bool, str)

    def __init__(self, transport, ops: List[Tuple[str, str, str]]) -> None:
        super().__init__()
        self._transport = transport
        self._ops = ops
        self._sftp = None
        self._cancelled = False

    def cancel(self) -> None:
        """GUI 스레드에서 호출: 플래그를 세우고 채널을 닫아 멈춘 송수신도 즉시 깨운다."""
        self._cancelled = True
        sftp = self._sftp
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass

    def was_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        current: Optional[Tuple[str, str, str]] = None
        try:
            self._sftp = sftp = _open_sftp(self._transport)
            sizes, total = [], 0
            for kind, src, _dst in self._ops:
                try:
                    sz = sftp.stat(src).st_size if kind == "get" else os.path.getsize(src)
                except Exception:
                    sz = 0
                sizes.append(sz)
                total += sz
            base = 0
            for (kind, src, dst), sz in zip(self._ops, sizes):
                if self._cancelled:
                    raise _TransferCancelled()
                current = (kind, src, dst)
                name = os.path.basename(dst) or posixpath.basename(src)

                def cb(done_b, _tot_b, _base=base, _name=name):
                    if self._cancelled:
                        raise _TransferCancelled()
                    pct = int((_base + done_b) * 100 / total) if total else 100
                    self.progress.emit(min(pct, 100), _name)

                if kind == "get":
                    sftp.get(src, dst, callback=cb)
                else:
                    sftp.put(src, dst, callback=cb)
                current = None
                base += sz
                self.progress.emit(int(base * 100 / total) if total else 100, name)
            self.done.emit(True, f"{len(self._ops)}개 항목 전송 완료")
        except Exception as exc:
            # 받다 만 로컬 파일은 지운다(불완전한 파일을 정상 파일로 오인 방지)
            if current is not None and current[0] == "get":
                try:
                    os.remove(current[2])
                except OSError:
                    pass
            if self._cancelled or isinstance(exc, _TransferCancelled):
                self.done.emit(False, "전송이 취소되었습니다.")
            else:
                self.done.emit(False, f"{type(exc).__name__}: {exc}")
        finally:
            if self._sftp is not None:
                try:
                    self._sftp.close()
                except Exception:
                    pass


class _SftpService(QThread):
    """원격 목록 조회/이름변경/새 폴더/삭제를 순차 처리하는 전용 스레드.

    paramiko SFTP 호출은 네트워크 왕복이라 UI 스레드에서 부르면 회선이 느리거나
    끊겼을 때 창 전체가 멈춘다. 모든 호출을 이 스레드로 모으고 결과만 시그널로 돌려준다.
    """

    # (seq, transport, 정규화 경로, [(이름, is_dir, 크기, mtime)], 오류메시지)
    listed = Signal(int, object, str, object, str)
    # (오류 목록) — 이름변경/새 폴더/삭제 완료
    op_done = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._jobs: "queue.Queue" = queue.Queue()
        self._sftp = None
        self._sftp_transport = None
        self._latest_list = 0  # 가장 최근 목록 요청 번호(이전 요청은 건너뜀)

    # ---- GUI 스레드에서 호출 ----
    def request_list(self, seq: int, transport, path: str) -> None:
        self._latest_list = seq
        self._jobs.put(("list", seq, transport, path))

    def request_ops(self, transport, ops: List[Tuple]) -> None:
        """ops: ("rename", old, new) | ("mkdir", path) | ("remove", path) | ("rmdir", path)"""
        self._jobs.put(("ops", transport, ops))

    def stop(self) -> None:
        self._jobs.put(None)

    # ---- 워커 스레드 ----
    def _drop_client(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
        self._sftp = None
        self._sftp_transport = None

    def _client(self, transport):
        if self._sftp is not None and self._sftp_transport is transport:
            return self._sftp
        self._drop_client()
        self._sftp = _open_sftp(transport)
        self._sftp_transport = transport
        return self._sftp

    def run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                break
            try:
                if job[0] == "list":
                    self._do_list(*job[1:])
                else:
                    self._do_ops(*job[1:])
            except Exception:
                self._drop_client()
        self._drop_client()

    def _do_list(self, seq: int, transport, path: str) -> None:
        if seq != self._latest_list:
            return  # 더 새로운 요청이 대기 중 → 건너뜀
        try:
            sftp = self._client(transport)
            norm = sftp.normalize(path)
            rows = [
                (
                    a.filename,
                    a.st_mode is not None and stat.S_ISDIR(a.st_mode),
                    a.st_size,
                    a.st_mtime,
                )
                for a in sftp.listdir_attr(norm)
            ]
        except Exception as exc:
            # 타임아웃 뒤의 SFTP 채널은 응답 순서가 어긋날 수 있으므로 버리고 다시 연다
            self._drop_client()
            self.listed.emit(seq, transport, path, [], f"{type(exc).__name__}: {exc}")
            return
        self.listed.emit(seq, transport, norm, rows, "")

    def _do_ops(self, transport, ops: List[Tuple]) -> None:
        errors: List[str] = []
        try:
            sftp = self._client(transport)
        except Exception as exc:
            self._drop_client()
            self.op_done.emit([f"{type(exc).__name__}: {exc}"])
            return
        for op in ops:
            kind, target = op[0], op[1]
            try:
                if kind == "rename":
                    sftp.rename(target, op[2])
                elif kind == "mkdir":
                    sftp.mkdir(target)
                elif kind == "rmdir":
                    sftp.rmdir(target)
                else:
                    sftp.remove(target)
            except (OSError, EOFError) as exc:
                errors.append(f"{posixpath.basename(target)}: {exc}")
                if isinstance(exc, (EOFError, TimeoutError)):  # 권한 오류 등은 계속 진행
                    self._drop_client()
                    break
            except Exception as exc:
                errors.append(f"{posixpath.basename(target)}: {exc}")
                self._drop_client()
                break
        self.op_done.emit(errors)


class FileBrowser(QWidget):
    def __init__(self, get_transport: Callable[[], object],
                 on_sync_toggled: Optional[Callable[[bool], None]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._get_transport = get_transport  # -> paramiko.Transport | None
        self._on_sync_toggled = on_sync_toggled
        self._remote_path = "."
        self._list_seq = 0            # 목록 요청 번호(늦게 온 이전 응답 폐기용)
        self._listed_transport = None  # 마지막으로 목록을 요청한 연결
        self._service = _SftpService()
        self._service.listed.connect(self._on_remote_listed)
        self._service.op_done.connect(self._on_remote_op_done)
        self._service.start()
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        self._local_path = docs if os.path.isdir(docs) else os.path.expanduser("~")
        self._worker: Optional[_SftpWorker] = None
        self._progress: Optional[QProgressDialog] = None
        self._icons = QFileIconProvider()

        self._build_ui()
        self.refresh_local()

    # ------------------------------------------------------------- UI
    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(["이름", "크기", "수정시간"])
        tree.setRootIsDecorated(False)
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.setUniformRowHeights(True)
        hdr = tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        return tree

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 리모트(상단) 박스 ──
        self.remote_path_edit = QLineEdit()
        self.remote_path_edit.returnPressed.connect(self._on_remote_path_entered)
        r_up = QPushButton("상위")
        r_ref = QPushButton("새로고침")
        for b in (r_up, r_ref):
            b.setProperty("variant", "subtle")
        r_up.clicked.connect(self._remote_up)
        r_ref.clicked.connect(self.refresh_remote)
        r_bar = QHBoxLayout()
        r_bar.setSpacing(4)
        r_bar.addWidget(self.remote_path_edit, 1)
        r_bar.addWidget(r_up)
        r_bar.addWidget(r_ref)

        self.remote_tree = self._make_tree()
        self.remote_tree.itemDoubleClicked.connect(self._on_remote_double)
        self.remote_tree.customContextMenuRequested.connect(self._remote_menu)

        self.sync_check = QCheckBox("터미널 경로 동기화")
        self.sync_check.setToolTip(
            "현재 터미널의 경로(cd)에 맞춰 리모트 목록을 자동 이동\n(OSC7 사용, bash 셸)"
        )
        self.sync_check.toggled.connect(self._sync_toggled)
        r_title = QLabel("리모트 (SSH) — 활성 터미널")
        r_title.setObjectName("sectionTitle")
        r_head = QHBoxLayout()
        r_head.addWidget(r_title)
        r_head.addStretch(1)
        r_head.addWidget(self.sync_check)

        remote_box = QWidget()
        rv = QVBoxLayout(remote_box)
        rv.setContentsMargins(0, 0, 0, 4)
        rv.setSpacing(6)
        rv.addLayout(r_head)
        rv.addLayout(r_bar)
        rv.addWidget(self.remote_tree, 1)

        # ── 로컬(하단) 박스 (전송 버튼을 상단에 두어 경계 바로 아래 배치) ──
        act = QHBoxLayout()
        act.setSpacing(6)
        btn_down = QPushButton("▼ 다운로드")
        btn_up = QPushButton("▲ 업로드")
        btn_down.setProperty("variant", "primary")
        btn_up.setProperty("variant", "primary")
        btn_down.clicked.connect(self._download)
        btn_up.clicked.connect(self._upload)
        act.addWidget(btn_down)
        act.addWidget(btn_up)

        self.local_path_edit = QLineEdit(self._local_path)
        self.local_path_edit.returnPressed.connect(self._on_local_path_entered)
        l_up = QPushButton("상위")
        l_browse = QPushButton("폴더 선택")
        l_ref = QPushButton("새로고침")
        for b in (l_up, l_browse, l_ref):
            b.setProperty("variant", "subtle")
        l_up.clicked.connect(self._local_up)
        l_browse.clicked.connect(self._browse_local)
        l_ref.clicked.connect(self.refresh_local)
        l_bar = QHBoxLayout()
        l_bar.setSpacing(4)
        l_bar.addWidget(self.local_path_edit, 1)
        l_bar.addWidget(l_up)
        l_bar.addWidget(l_browse)
        l_bar.addWidget(l_ref)

        self.local_tree = self._make_tree()
        self.local_tree.itemDoubleClicked.connect(self._on_local_double)
        self.local_tree.customContextMenuRequested.connect(self._local_menu)

        l_title = QLabel("로컬 PC")
        l_title.setObjectName("sectionTitle")
        local_box = QWidget()
        lv = QVBoxLayout(local_box)
        lv.setContentsMargins(0, 4, 0, 0)
        lv.setSpacing(6)
        lv.addLayout(act)
        lv.addWidget(l_title)
        lv.addLayout(l_bar)
        lv.addWidget(self.local_tree, 1)

        # ── 리모트/로컬 경계를 드래그로 조절(세로 스플리터) ──
        split = QSplitter(Qt.Vertical)
        split.addWidget(remote_box)
        split.addWidget(local_box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setHandleWidth(5)
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)

    # --------------------------------------------------------- 아이콘/항목
    def _icon_for(self, name: str, is_dir: bool, local_full: Optional[str]):
        if is_dir:
            return self._icons.icon(QFileIconProvider.IconType.Folder)
        if local_full is not None:
            return self._icons.icon(QFileInfo(local_full))
        icon = self._icons.icon(QFileInfo(name))  # 원격: 확장자 기반
        if icon.isNull():
            return self._icons.icon(QFileIconProvider.IconType.File)
        return icon

    def _add_row(self, tree, name, is_dir, size, mtime, local_full=None) -> None:
        size_txt = "" if is_dir else _human_size(size)
        item = QTreeWidgetItem([name, size_txt, _fmt_time(mtime)])
        item.setData(0, _ROLE_NAME, name)
        item.setData(0, _ROLE_ISDIR, is_dir)
        item.setIcon(0, self._icon_for(name, is_dir, local_full))
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        tree.addTopLevelItem(item)

    # --------------------------------------------------------- 원격(SFTP)
    def _remote_transport(self):
        """활성 연결의 transport. 없으면 None."""
        transport = self._get_transport()
        if transport is None or not transport.is_active():
            return None
        return transport

    def refresh_remote(self) -> None:
        """원격 목록을 비동기로 다시 읽는다(결과는 _on_remote_listed 로 도착)."""
        self.remote_tree.clear()
        transport = self._remote_transport()
        self._list_seq += 1  # 진행 중이던 이전 요청의 응답은 폐기
        if transport is None:
            self._listed_transport = None
            self.remote_path_edit.setText("")
            self._add_row(self.remote_tree, "연결된 터미널이 없습니다", False, None, None)
            return
        if transport is not self._listed_transport:
            # 새(다른) 연결이면 이전 서버의 경로가 유효하지 않으므로 홈으로 초기화
            self._listed_transport = transport
            self._remote_path = "."
        self._add_row(self.remote_tree, "[불러오는 중...]", False, None, None)
        self._service.request_list(self._list_seq, transport, self._remote_path)

    def _on_remote_listed(self, seq: int, transport, path: str, rows, error: str) -> None:
        if seq != self._list_seq or transport is not self._listed_transport:
            return  # 그 사이 다른 경로/연결을 요청함
        self.remote_tree.clear()
        if error:
            self._add_row(self.remote_tree, f"[오류] {error}", False, None, None)
            return
        self._remote_path = path
        self.remote_path_edit.setText(path)
        if path not in ("/", ""):
            self._add_row(self.remote_tree, "..", True, None, None)
        self.remote_tree.setUpdatesEnabled(False)
        try:
            for name, _d, _size, mtime in sorted(
                (r for r in rows if r[1]), key=lambda r: r[0].lower()
            ):
                self._add_row(self.remote_tree, name, True, None, mtime)
            for name, _d, size, mtime in sorted(
                (r for r in rows if not r[1]), key=lambda r: r[0].lower()
            ):
                self._add_row(self.remote_tree, name, False, size, mtime)
        finally:
            self.remote_tree.setUpdatesEnabled(True)

    def _run_remote_ops(self, ops: List[Tuple]) -> None:
        transport = self._remote_transport()
        if transport is None:
            QMessageBox.warning(self, "안내", "연결된 터미널이 없습니다.")
            return
        self._service.request_ops(transport, ops)

    def _on_remote_op_done(self, errors) -> None:
        self.refresh_remote()
        if errors:
            QMessageBox.warning(self, "일부 실패", "\n".join(errors[:10]))

    def shutdown(self) -> None:
        """앱 종료 시: 진행 중 전송을 취소하고 워커 스레드를 정리."""
        self._list_seq += 1
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        self._service.stop()
        self._service.wait(2000)

    def _on_remote_double(self, item: QTreeWidgetItem, _col: int) -> None:
        name = item.data(0, _ROLE_NAME)
        if not name or not item.data(0, _ROLE_ISDIR):
            return
        if name == "..":
            self._remote_path = posixpath.dirname(self._remote_path.rstrip("/")) or "/"
        else:
            self._remote_path = posixpath.join(self._remote_path, name)
        self.refresh_remote()

    def _remote_up(self) -> None:
        self._remote_path = posixpath.dirname(self._remote_path.rstrip("/")) or "/"
        self.refresh_remote()

    def _on_remote_path_entered(self) -> None:
        self._remote_path = self.remote_path_edit.text().strip() or "."
        self.refresh_remote()

    # ----------------------------------------------------- 경로 동기화
    def sync_enabled(self) -> bool:
        return self.sync_check.isChecked()

    def _sync_toggled(self, checked: bool) -> None:
        if self._on_sync_toggled is not None:
            self._on_sync_toggled(checked)

    def set_remote_path(self, path: str) -> None:
        """외부(터미널 동기화)에서 원격 경로를 지정하고 목록 갱신."""
        if path and path != self._remote_path:
            self._remote_path = path
            self.refresh_remote()

    # --------------------------------------------------------- 로컬
    def refresh_local(self) -> None:
        self.local_tree.clear()
        path = self._local_path
        self.local_path_edit.setText(path)
        try:
            names = os.listdir(path)
        except Exception as exc:
            self._add_row(self.local_tree, f"[오류] {exc}", False, None, None)
            return
        parent = os.path.dirname(os.path.normpath(path))
        if parent and parent != os.path.normpath(path):
            self._add_row(self.local_tree, "..", True, None, None)
        dirs, files = [], []
        for n in names:
            full = os.path.join(path, n)
            (dirs if os.path.isdir(full) else files).append(n)
        for n in sorted(dirs, key=str.lower):
            full = os.path.join(path, n)
            mtime = self._safe_mtime(full)
            self._add_row(self.local_tree, n, True, None, mtime, local_full=full)
        for n in sorted(files, key=str.lower):
            full = os.path.join(path, n)
            size, mtime = self._safe_stat(full)
            self._add_row(self.local_tree, n, False, size, mtime, local_full=full)

    @staticmethod
    def _safe_stat(full):
        try:
            st = os.stat(full)
            return st.st_size, st.st_mtime
        except Exception:
            return None, None

    @staticmethod
    def _safe_mtime(full):
        try:
            return os.stat(full).st_mtime
        except Exception:
            return None

    def _on_local_double(self, item: QTreeWidgetItem, _col: int) -> None:
        name = item.data(0, _ROLE_NAME)
        if not name or not item.data(0, _ROLE_ISDIR):
            return
        if name == "..":
            self._local_path = os.path.dirname(os.path.normpath(self._local_path))
        else:
            self._local_path = os.path.join(self._local_path, name)
        self.refresh_local()

    def _local_up(self) -> None:
        self._local_path = os.path.dirname(os.path.normpath(self._local_path))
        self.refresh_local()

    def _browse_local(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "로컬 폴더 선택", self._local_path)
        if path:
            self._local_path = path
            self.refresh_local()

    def _on_local_path_entered(self) -> None:
        p = self.local_path_edit.text().strip()
        if os.path.isdir(p):
            self._local_path = p
        self.refresh_local()

    # --------------------------------------------------------- 우클릭 메뉴
    def _remote_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("▼ 다운로드", self._download)
        menu.addAction("이름 변경...", self._rename_remote)
        menu.addAction("새 폴더...", self._mkdir_remote)
        menu.addAction("삭제", self._delete_remote)
        menu.addSeparator()
        menu.addAction("새로고침", self.refresh_remote)
        menu.exec(self.remote_tree.viewport().mapToGlobal(pos))

    def _local_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("▲ 업로드", self._upload)
        menu.addAction("이름 변경...", self._rename_local)
        menu.addAction("새 폴더...", self._mkdir_local)
        menu.addAction("삭제", self._delete_local)
        menu.addSeparator()
        menu.addAction("새로고침", self.refresh_local)
        menu.exec(self.local_tree.viewport().mapToGlobal(pos))

    # --------------------------------------------------------- 선택/전송
    def _selected(self, tree) -> List[Tuple[str, bool]]:
        out = []
        for it in tree.selectedItems():
            name = it.data(0, _ROLE_NAME)
            if name and name != ".." and not str(name).startswith("["):
                out.append((name, bool(it.data(0, _ROLE_ISDIR))))
        return out

    def _download(self) -> None:
        files = [n for n, d in self._selected(self.remote_tree) if not d]
        if not files:
            QMessageBox.information(self, "안내", "다운로드할 원격 파일을 선택하세요. (폴더 제외)")
            return
        if not os.path.isdir(self._local_path):
            QMessageBox.warning(self, "안내", "로컬 폴더가 유효하지 않습니다.")
            return
        unsafe = [n for n in files if not is_safe_local_name(n)]
        if unsafe:
            QMessageBox.warning(
                self,
                "다운로드 제외",
                "경로 문자가 포함된 파일명은 로컬 폴더 밖에 쓰일 수 있어 제외합니다:\n\n"
                + "\n".join(f"  • {n!r}" for n in unsafe[:10]),
            )
            files = [n for n in files if n not in unsafe]
            if not files:
                return
        existing = [n for n in files if os.path.lexists(os.path.join(self._local_path, n))]
        if existing and not self._confirm_overwrite("로컬", existing):
            return
        ops = [
            ("get", posixpath.join(self._remote_path, n), os.path.join(self._local_path, n))
            for n in files
        ]
        self._run_transfer(ops)

    def _confirm_overwrite(self, side: str, names: List[str]) -> bool:
        shown = "\n".join(f"  • {n}" for n in names[:15])
        more = f"\n  … 외 {len(names) - 15}개" if len(names) > 15 else ""
        return QMessageBox.warning(
            self,
            "덮어쓰기 확인",
            f"{side}에 같은 이름의 항목이 이미 있습니다:\n\n{shown}{more}\n\n덮어쓸까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

    def _remote_names(self) -> set:
        """현재 표시 중인 원격 목록의 이름들(업로드 덮어쓰기 확인용)."""
        out = set()
        for i in range(self.remote_tree.topLevelItemCount()):
            name = self.remote_tree.topLevelItem(i).data(0, _ROLE_NAME)
            if name and name != "..":
                out.add(name)
        return out

    def _upload(self) -> None:
        files = [n for n, d in self._selected(self.local_tree) if not d]
        if not files:
            QMessageBox.information(self, "안내", "업로드할 로컬 파일을 선택하세요. (폴더 제외)")
            return
        remote_names = self._remote_names()
        existing = [n for n in files if n in remote_names]
        if existing and not self._confirm_overwrite("원격", existing):
            return
        ops = [
            ("put", os.path.join(self._local_path, n), posixpath.join(self._remote_path, n))
            for n in files
        ]
        self._run_transfer(ops)

    def _run_transfer(self, ops: List[Tuple[str, str, str]]) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "안내", "이미 전송 중입니다.")
            return
        transport = self._get_transport()
        if transport is None or not transport.is_active():
            QMessageBox.warning(self, "안내", "연결된 터미널이 없습니다.")
            return
        self._progress = QProgressDialog(f"{len(ops)}개 파일 전송 중...", "취소", 0, 100, self)
        self._progress.setWindowTitle("파일 전송")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setValue(0)
        self._worker = _SftpWorker(transport, ops)
        self._worker.progress.connect(self._on_transfer_progress)
        self._worker.done.connect(self._on_transfer_done)
        self._progress.canceled.connect(self._on_transfer_cancel)
        self._worker.start()
        self._progress.show()

    def _on_transfer_progress(self, pct: int, name: str) -> None:
        if self._progress is not None:
            self._progress.setLabelText(f"{name}  —  {pct}%")
            self._progress.setValue(pct)

    def _on_transfer_cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()  # 완료 처리는 done 시그널에서

    def _on_transfer_done(self, ok: bool, msg: str) -> None:
        if self._progress is not None:
            try:
                self._progress.canceled.disconnect()  # close() 가 canceled 를 내보내는 것 방지
            except Exception:
                pass
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None
        self.refresh_remote()
        self.refresh_local()
        cancelled = self._worker is not None and self._worker.was_cancelled()
        if ok:
            QMessageBox.information(self, "전송 완료", msg)
        elif cancelled:
            QMessageBox.information(self, "전송 취소", msg)
        else:
            QMessageBox.critical(self, "전송 실패", msg)

    # --------------------------------------------------------- 이름변경/새폴더
    def _rename_remote(self) -> None:
        sel = self._selected(self.remote_tree)
        if len(sel) != 1:
            QMessageBox.information(self, "안내", "이름을 변경할 항목 1개를 선택하세요.")
            return
        old = sel[0][0]
        new, ok = QInputDialog.getText(self, "이름 변경", "새 이름:", text=old)
        if not ok or not new.strip() or new == old:
            return
        self._run_remote_ops([(
            "rename",
            posixpath.join(self._remote_path, old),
            posixpath.join(self._remote_path, new.strip()),
        )])

    def _mkdir_remote(self) -> None:
        name, ok = QInputDialog.getText(self, "새 폴더", "폴더 이름:")
        if not ok or not name.strip():
            return
        self._run_remote_ops([("mkdir", posixpath.join(self._remote_path, name.strip()))])

    def _rename_local(self) -> None:
        sel = self._selected(self.local_tree)
        if len(sel) != 1:
            QMessageBox.information(self, "안내", "이름을 변경할 항목 1개를 선택하세요.")
            return
        old = sel[0][0]
        new, ok = QInputDialog.getText(self, "이름 변경", "새 이름:", text=old)
        if not ok or not new.strip() or new == old:
            return
        try:
            os.rename(
                os.path.join(self._local_path, old),
                os.path.join(self._local_path, new.strip()),
            )
        except Exception as exc:
            QMessageBox.warning(self, "실패", str(exc))
        self.refresh_local()

    def _mkdir_local(self) -> None:
        name, ok = QInputDialog.getText(self, "새 폴더", "폴더 이름:")
        if not ok or not name.strip():
            return
        try:
            os.mkdir(os.path.join(self._local_path, name.strip()))
        except Exception as exc:
            QMessageBox.warning(self, "실패", str(exc))
        self.refresh_local()

    # --------------------------------------------------------- 삭제(확인 필수)
    def _delete_remote(self) -> None:
        sel = self._selected(self.remote_tree)
        if not sel:
            return
        names = "\n".join(f"  • {n}" for n, _ in sel[:15])
        if QMessageBox.warning(
            self,
            "원격 삭제 확인",
            f"다음 원격 항목을 삭제합니다:\n\n{names}\n\n삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._run_remote_ops([
            ("rmdir" if is_dir else "remove", posixpath.join(self._remote_path, name))
            for name, is_dir in sel
        ])

    def _delete_local(self) -> None:
        sel = self._selected(self.local_tree)
        if not sel:
            return
        names = "\n".join(f"  • {n}" for n, _ in sel[:15])
        if QMessageBox.warning(
            self,
            "로컬 삭제 확인",
            f"다음 로컬 항목을 삭제합니다:\n\n{names}\n\n삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        errors = []
        for name, is_dir in sel:
            full = os.path.join(self._local_path, name)
            try:
                if is_dir:
                    os.rmdir(full)
                else:
                    os.remove(full)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        self.refresh_local()
        if errors:
            QMessageBox.warning(self, "일부 실패", "\n".join(errors[:10]))
