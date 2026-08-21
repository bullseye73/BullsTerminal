"""SFTP 파일 브라우저 (WinSCP 스타일).

상단: SSH 접속된 리모트 PC의 현재 위치, 하단: 로컬 PC(기본 내 문서).
- 시스템 아이콘(QFileIconProvider), 크기/수정시간 컬럼
- 우클릭 메뉴(다운로드/업로드/이름변경/새 폴더/삭제/새로고침)
- 삭제 확인 팝업, 전송 진행률(%) 표시
- 전송은 백그라운드 스레드로 수행(GUI 프리징 방지)
"""
from __future__ import annotations

import os
import posixpath
import stat
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QFileInfo, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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


class _SftpWorker(QThread):
    """백그라운드 파일 전송 (get/put) + 진행률."""

    progress = Signal(int, str)  # percent(0-100), filename
    done = Signal(bool, str)

    def __init__(self, transport, ops: List[Tuple[str, str, str]]) -> None:
        super().__init__()
        self._transport = transport
        self._ops = ops

    def run(self) -> None:
        sftp = None
        try:
            sftp = self._transport.open_sftp_client()
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
                name = os.path.basename(dst) or posixpath.basename(src)

                def cb(done_b, _tot_b, _base=base, _name=name):
                    pct = int((_base + done_b) * 100 / total) if total else 100
                    self.progress.emit(min(pct, 100), _name)

                if kind == "get":
                    sftp.get(src, dst, callback=cb)
                else:
                    sftp.put(src, dst, callback=cb)
                base += sz
                self.progress.emit(int(base * 100 / total) if total else 100, name)
            self.done.emit(True, f"{len(self._ops)}개 항목 전송 완료")
        except Exception as exc:
            self.done.emit(False, f"{type(exc).__name__}: {exc}")
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass


class FileBrowser(QWidget):
    def __init__(self, get_transport: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._get_transport = get_transport  # -> paramiko.Transport | None
        self._sftp = None
        self._sftp_transport = None
        self._remote_path = "."
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
        layout.setContentsMargins(4, 4, 4, 4)

        # ── 리모트(상단) 박스 ──
        self.remote_path_edit = QLineEdit()
        self.remote_path_edit.returnPressed.connect(self._on_remote_path_entered)
        r_up = QPushButton("상위")
        r_ref = QPushButton("새로고침")
        r_up.clicked.connect(self._remote_up)
        r_ref.clicked.connect(self.refresh_remote)
        r_bar = QHBoxLayout()
        r_bar.addWidget(self.remote_path_edit, 1)
        r_bar.addWidget(r_up)
        r_bar.addWidget(r_ref)

        self.remote_tree = self._make_tree()
        self.remote_tree.itemDoubleClicked.connect(self._on_remote_double)
        self.remote_tree.customContextMenuRequested.connect(self._remote_menu)

        remote_box = QWidget()
        rv = QVBoxLayout(remote_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("리모트 (SSH) — 활성 터미널 연결"))
        rv.addLayout(r_bar)
        rv.addWidget(self.remote_tree, 1)

        # ── 로컬(하단) 박스 (전송 버튼을 상단에 두어 경계 바로 아래 배치) ──
        act = QHBoxLayout()
        btn_down = QPushButton("▼ 다운로드")
        btn_up = QPushButton("▲ 업로드")
        btn_down.clicked.connect(self._download)
        btn_up.clicked.connect(self._upload)
        act.addWidget(btn_down)
        act.addWidget(btn_up)

        self.local_path_edit = QLineEdit(self._local_path)
        self.local_path_edit.returnPressed.connect(self._on_local_path_entered)
        l_up = QPushButton("상위")
        l_browse = QPushButton("폴더 선택")
        l_ref = QPushButton("새로고침")
        l_up.clicked.connect(self._local_up)
        l_browse.clicked.connect(self._browse_local)
        l_ref.clicked.connect(self.refresh_local)
        l_bar = QHBoxLayout()
        l_bar.addWidget(self.local_path_edit, 1)
        l_bar.addWidget(l_up)
        l_bar.addWidget(l_browse)
        l_bar.addWidget(l_ref)

        self.local_tree = self._make_tree()
        self.local_tree.itemDoubleClicked.connect(self._on_local_double)
        self.local_tree.customContextMenuRequested.connect(self._local_menu)

        local_box = QWidget()
        lv = QVBoxLayout(local_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addLayout(act)
        lv.addWidget(QLabel("로컬 PC"))
        lv.addLayout(l_bar)
        lv.addWidget(self.local_tree, 1)

        # ── 리모트/로컬 경계를 드래그로 조절(세로 스플리터) ──
        split = QSplitter(Qt.Vertical)
        split.addWidget(remote_box)
        split.addWidget(local_box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setHandleWidth(8)
        split.setChildrenCollapsible(False)
        split.setStyleSheet(
            "QSplitter::handle { background: #c0c0c0; margin: 2px 4px; border-radius: 2px; }"
        )
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
    def _ensure_sftp(self):
        transport = self._get_transport()
        if transport is None or not transport.is_active():
            if self._sftp is not None:
                try:
                    self._sftp.close()
                except Exception:
                    pass
            self._sftp = None
            self._sftp_transport = None
            return None
        if self._sftp is not None and self._sftp_transport is transport:
            return self._sftp
        try:
            if self._sftp is not None:
                self._sftp.close()
        except Exception:
            pass
        self._sftp = transport.open_sftp_client()
        self._sftp_transport = transport
        # 새(다른) 연결이면 이전 서버의 경로가 유효하지 않으므로 홈으로 초기화
        self._remote_path = "."
        return self._sftp

    def refresh_remote(self) -> None:
        self.remote_tree.clear()
        sftp = self._ensure_sftp()
        if sftp is None:
            self.remote_path_edit.setText("")
            self._add_row(self.remote_tree, "연결된 터미널이 없습니다", False, None, None)
            return
        try:
            norm = sftp.normalize(self._remote_path)
            self._remote_path = norm
            entries = sftp.listdir_attr(norm)
        except Exception as exc:
            self._add_row(self.remote_tree, f"[오류] {exc}", False, None, None)
            return
        self.remote_path_edit.setText(norm)
        if norm not in ("/", ""):
            self._add_row(self.remote_tree, "..", True, None, None)
        dirs, files = [], []
        for a in entries:
            is_dir = a.st_mode is not None and stat.S_ISDIR(a.st_mode)
            (dirs if is_dir else files).append(a)
        for a in sorted(dirs, key=lambda x: x.filename.lower()):
            self._add_row(self.remote_tree, a.filename, True, None, a.st_mtime)
        for a in sorted(files, key=lambda x: x.filename.lower()):
            self._add_row(self.remote_tree, a.filename, False, a.st_size, a.st_mtime)

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
        ops = [
            ("get", posixpath.join(self._remote_path, n), os.path.join(self._local_path, n))
            for n in files
        ]
        self._run_transfer(ops)

    def _upload(self) -> None:
        files = [n for n, d in self._selected(self.local_tree) if not d]
        if not files:
            QMessageBox.information(self, "안내", "업로드할 로컬 파일을 선택하세요. (폴더 제외)")
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
        self._progress = QProgressDialog(f"{len(ops)}개 파일 전송 중...", None, 0, 100, self)
        self._progress.setWindowTitle("파일 전송")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setValue(0)
        self._worker = _SftpWorker(transport, ops)
        self._worker.progress.connect(self._on_transfer_progress)
        self._worker.done.connect(self._on_transfer_done)
        self._worker.start()
        self._progress.show()

    def _on_transfer_progress(self, pct: int, name: str) -> None:
        if self._progress is not None:
            self._progress.setLabelText(f"{name}  —  {pct}%")
            self._progress.setValue(pct)

    def _on_transfer_done(self, ok: bool, msg: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None
        self.refresh_remote()
        self.refresh_local()
        if ok:
            QMessageBox.information(self, "전송 완료", msg)
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
        sftp = self._ensure_sftp()
        if sftp is None:
            return
        try:
            sftp.rename(
                posixpath.join(self._remote_path, old),
                posixpath.join(self._remote_path, new.strip()),
            )
        except Exception as exc:
            QMessageBox.warning(self, "실패", str(exc))
        self.refresh_remote()

    def _mkdir_remote(self) -> None:
        name, ok = QInputDialog.getText(self, "새 폴더", "폴더 이름:")
        if not ok or not name.strip():
            return
        sftp = self._ensure_sftp()
        if sftp is None:
            return
        try:
            sftp.mkdir(posixpath.join(self._remote_path, name.strip()))
        except Exception as exc:
            QMessageBox.warning(self, "실패", str(exc))
        self.refresh_remote()

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
        sftp = self._ensure_sftp()
        if sftp is None:
            return
        errors = []
        for name, is_dir in sel:
            full = posixpath.join(self._remote_path, name)
            try:
                if is_dir:
                    sftp.rmdir(full)
                else:
                    sftp.remove(full)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        self.refresh_remote()
        if errors:
            QMessageBox.warning(self, "일부 실패", "\n".join(errors[:10]))

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
