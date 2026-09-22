"""유틸 탭: Base64 인코딩 / 디코딩.

도구 도크(클립보드 / 파일 / 유틸)의 세 번째 탭. 위쪽에 입력, 아래쪽에 결과를 두고
가운데 버튼으로 방향(인코딩 ▼ / 디코딩 ▲)을 고른다. 결과는 클립보드로 복사하거나
명령 입력창으로 바로 보낼 수 있다.
"""
from __future__ import annotations

import base64
import binascii
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# 디코딩 시 허용할 문자(표준 + URL-safe 알파벳, 패딩 포함)
_B64_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/-_="
)


def encode_base64(text: str, url_safe: bool = False) -> str:
    """문자열을 UTF-8 로 인코딩한 뒤 Base64 문자열로 변환."""
    raw = text.encode("utf-8")
    out = base64.urlsafe_b64encode(raw) if url_safe else base64.b64encode(raw)
    return out.decode("ascii")


def decode_base64(text: str) -> "tuple[str, bool]":
    """Base64 문자열을 디코딩.

    공백/줄바꿈은 무시하고, URL-safe(`-_`) 알파벳과 빠진 패딩(`=`)도 받아들인다.
    반환값은 (디코딩 결과, UTF-8 로 온전히 해석됐는지 여부).
    UTF-8 이 아니면 깨진 바이트를 `\\xNN` 로 표시해 돌려준다.
    잘못된 입력은 ValueError.
    """
    compact = "".join(text.split())
    if not compact:
        raise ValueError("입력이 비어 있습니다.")
    bad = {c for c in compact if c not in _B64_CHARS}
    if bad:
        sample = "".join(sorted(bad)[:5])
        raise ValueError(f"Base64 에 쓸 수 없는 문자가 있습니다: {sample}")

    normalized = compact.replace("-", "+").replace("_", "/").rstrip("=")
    if len(normalized) % 4 == 1:
        raise ValueError("Base64 길이가 올바르지 않습니다.")
    padded = normalized + "=" * (-len(normalized) % 4)
    try:
        raw = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Base64 디코딩 실패: {exc}") from exc

    try:
        return raw.decode("utf-8"), True
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="backslashreplace"), False


class UtilPanel(QWidget):
    """Base64 인코딩/디코딩 패널."""

    def __init__(
        self,
        on_send_to_command: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_send_to_command = on_send_to_command
        self._build_ui()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        # ---- 입력 ----
        self.src = QPlainTextEdit()
        self.src.setPlaceholderText("인코딩할 문자열 또는 디코딩할 Base64 를 입력/붙여넣기")
        self.src.setTabChangesFocus(True)

        src_paste = QPushButton("붙여넣기")
        src_paste.setToolTip("시스템 클립보드 내용을 입력에 넣기")
        src_paste.clicked.connect(self._on_paste)
        src_clear = QPushButton("지우기")
        src_clear.setToolTip("입력과 결과를 모두 비우기")
        src_clear.clicked.connect(self._on_clear)

        src_head = QHBoxLayout()
        src_head.addWidget(QLabel("입력"))
        src_head.addStretch(1)
        src_head.addWidget(src_paste)
        src_head.addWidget(src_clear)

        src_box = QWidget()
        src_layout = QVBoxLayout(src_box)
        src_layout.setContentsMargins(0, 0, 0, 0)
        src_layout.addLayout(src_head)
        src_layout.addWidget(self.src, 1)

        # ---- 결과 ----
        self.dst = QPlainTextEdit()
        self.dst.setPlaceholderText("결과가 여기에 표시됩니다 (편집 가능)")
        self.dst.setTabChangesFocus(True)

        dst_copy = QPushButton("복사")
        dst_copy.setToolTip("결과를 클립보드로 복사")
        dst_copy.clicked.connect(self._on_copy)
        self.dst_send = QPushButton("입력창으로")
        self.dst_send.setToolTip("결과를 아래 명령 입력창으로 보내기")
        self.dst_send.clicked.connect(self._on_send)
        self.dst_send.setEnabled(self._on_send_to_command is not None)

        dst_head = QHBoxLayout()
        dst_head.addWidget(QLabel("결과"))
        dst_head.addStretch(1)
        dst_head.addWidget(dst_copy)
        dst_head.addWidget(self.dst_send)

        dst_box = QWidget()
        dst_layout = QVBoxLayout(dst_box)
        dst_layout.setContentsMargins(0, 0, 0, 0)
        dst_layout.addLayout(dst_head)
        dst_layout.addWidget(self.dst, 1)

        # ---- 가운데 실행 버튼 ----
        enc_btn = QPushButton("▼ 인코딩")
        enc_btn.setToolTip("입력 문자열 → Base64 (UTF-8 기준)")
        enc_btn.clicked.connect(self._on_encode)
        dec_btn = QPushButton("▲ 디코딩")
        dec_btn.setToolTip("입력 Base64 → 문자열 (공백/줄바꿈·패딩 누락 허용)")
        dec_btn.clicked.connect(self._on_decode)
        swap_btn = QPushButton("결과 → 입력")
        swap_btn.setToolTip("결과를 입력으로 올려 연속 변환 (인코딩 후 바로 디코딩 확인 등)")
        swap_btn.clicked.connect(self._on_swap)

        self.url_safe = QCheckBox("URL-safe")
        self.url_safe.setToolTip(
            "인코딩 결과에 +/ 대신 -_ 사용 (JWT·URL 파라미터용).\n"
            "디코딩은 두 방식 모두 자동으로 인식합니다."
        )

        # 도크가 좁아도 접히지 않도록 두 줄로 나눈다.
        act_row = QHBoxLayout()
        act_row.addWidget(enc_btn, 1)
        act_row.addWidget(dec_btn, 1)
        opt_row = QHBoxLayout()
        opt_row.addWidget(swap_btn)
        opt_row.addWidget(self.url_safe)
        opt_row.addStretch(1)

        # ---- 조립 ----
        split = QSplitter(Qt.Vertical)
        split.addWidget(src_box)
        split.addWidget(dst_box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 200])
        split.setHandleWidth(8)
        split.setStyleSheet(
            "QSplitter::handle { background: #c0c0c0; margin: 2px 0; border-radius: 2px; }"
        )

        self.status = QLabel("문자열을 입력하고 [▼ 인코딩] 또는 [▲ 디코딩]을 누르세요.")
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(split, 1)
        layout.addLayout(act_row)
        layout.addLayout(opt_row)
        layout.addWidget(self.status)

    # ------------------------------------------------------------ 외부 API
    def apply_font(self, font: QFont) -> None:
        """입력/결과 편집기에 앱 공용 폰트 적용."""
        self.src.setFont(font)
        self.dst.setFont(font)

    # -------------------------------------------------------------- 동작들
    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setStyleSheet("color:#c0392b;" if error else "")
        self.status.setText(text)

    def _on_encode(self) -> None:
        text = self.src.toPlainText()
        if not text:
            self._set_status("입력이 비어 있습니다.", error=True)
            return
        out = encode_base64(text, url_safe=self.url_safe.isChecked())
        self.dst.setPlainText(out)
        kind = "URL-safe Base64" if self.url_safe.isChecked() else "Base64"
        self._set_status(
            f"인코딩 완료 — 입력 {len(text.encode('utf-8'))}바이트 → {kind} {len(out)}자"
        )

    def _on_decode(self) -> None:
        try:
            out, is_utf8 = decode_base64(self.src.toPlainText())
        except ValueError as exc:
            self.dst.clear()
            self._set_status(str(exc), error=True)
            return
        self.dst.setPlainText(out)
        if is_utf8:
            self._set_status(f"디코딩 완료 — {len(out)}자")
        else:
            self._set_status(
                "디코딩했지만 UTF-8 텍스트가 아닙니다. 깨진 바이트는 \\xNN 로 표시했습니다.",
                error=True,
            )

    def _on_swap(self) -> None:
        out = self.dst.toPlainText()
        if not out:
            self._set_status("결과가 비어 있습니다.", error=True)
            return
        self.src.setPlainText(out)
        self.dst.clear()
        self._set_status("결과를 입력으로 옮겼습니다.")

    def _on_copy(self) -> None:
        out = self.dst.toPlainText()
        if not out:
            self._set_status("복사할 결과가 없습니다.", error=True)
            return
        QApplication.clipboard().setText(out)
        self._set_status(f"결과 {len(out)}자를 클립보드로 복사했습니다.")

    def _on_paste(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            self._set_status("클립보드가 비어 있습니다.", error=True)
            return
        self.src.setPlainText(text)
        self._set_status(f"클립보드 {len(text)}자를 입력에 넣었습니다.")

    def _on_clear(self) -> None:
        self.src.clear()
        self.dst.clear()
        self._set_status("비웠습니다.")

    def _on_send(self) -> None:
        out = self.dst.toPlainText()
        if not out:
            self._set_status("보낼 결과가 없습니다.", error=True)
            return
        if self._on_send_to_command is None:
            return
        self._on_send_to_command(out)
        self._set_status("결과를 명령 입력창으로 보냈습니다.")
