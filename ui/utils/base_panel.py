"""유틸 패널 공통 틀.

위쪽 `입력` / 아래쪽 `결과` 두 칸과 공통 버튼(붙여넣기·지우기·복사·입력창으로·결과→입력),
상태 표시줄을 제공한다. 새 유틸은 이 클래스를 상속해서

    * `INPUT_HINT` / `START_HINT` 문구를 정하고
    * `action_rows()` 에 동작 버튼 줄(들)을,
    * 필요하면 `option_widgets()` 에 옵션 위젯을

돌려주면 나머지 레이아웃·클립보드 연동은 그대로 재사용된다.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class TextUtilPanel(QWidget):
    """텍스트 입력 → 변환 → 결과 형태의 유틸 패널 기반 클래스."""

    INPUT_HINT = "변환할 내용을 입력/붙여넣기"
    RESULT_HINT = "결과가 여기에 표시됩니다 (편집 가능)"
    START_HINT = "내용을 입력한 뒤 아래 버튼을 누르세요."

    def __init__(
        self,
        on_send_to_command: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_send_to_command = on_send_to_command
        self._build_ui()

    # ------------------------------------------------- 하위 클래스가 채우는 부분
    def action_rows(self) -> List[QHBoxLayout]:
        """동작 버튼 줄들(위에서 아래 순서). 하위 클래스에서 구현."""
        return []

    def option_widgets(self) -> List[QWidget]:
        """마지막 줄('결과 → 입력' 옆)에 붙일 옵션 위젯들."""
        return []

    # ---------------------------------------------------------------- UI 구성
    def _build_ui(self) -> None:
        self.src = QPlainTextEdit()
        self.src.setPlaceholderText(self.INPUT_HINT)
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

        self.dst = QPlainTextEdit()
        self.dst.setPlaceholderText(self.RESULT_HINT)
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

        swap_btn = QPushButton("결과 → 입력")
        swap_btn.setToolTip("결과를 입력으로 올려 연속 변환 (변환 후 바로 되돌려 확인 등)")
        swap_btn.clicked.connect(self._on_swap)
        last_row = QHBoxLayout()
        last_row.addWidget(swap_btn)
        for w in self.option_widgets():
            last_row.addWidget(w)
        last_row.addStretch(1)

        self.status = QLabel(self.START_HINT)
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(split, 1)
        for row in self.action_rows():
            layout.addLayout(row)
        layout.addLayout(last_row)
        layout.addWidget(self.status)

    # ------------------------------------------------------------- 공통 동작
    def apply_font(self, font: QFont) -> None:
        """입력/결과 편집기에 앱 공용 폰트 적용."""
        self.src.setFont(font)
        self.dst.setFont(font)

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setStyleSheet("color:#c0392b;" if error else "")
        self.status.setText(text)

    def source_text(self) -> str:
        return self.src.toPlainText()

    def set_result(self, text: str) -> None:
        self.dst.setPlainText(text)

    def _on_swap(self) -> None:
        out = self.dst.toPlainText()
        if not out:
            self.set_status("결과가 비어 있습니다.", error=True)
            return
        self.src.setPlainText(out)
        self.dst.clear()
        self.set_status("결과를 입력으로 옮겼습니다.")

    def _on_copy(self) -> None:
        out = self.dst.toPlainText()
        if not out:
            self.set_status("복사할 결과가 없습니다.", error=True)
            return
        QApplication.clipboard().setText(out)
        self.set_status(f"결과 {len(out)}자를 클립보드로 복사했습니다.")

    def _on_paste(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            self.set_status("클립보드가 비어 있습니다.", error=True)
            return
        self.src.setPlainText(text)
        self.set_status(f"클립보드 {len(text)}자를 입력에 넣었습니다.")

    def _on_clear(self) -> None:
        self.src.clear()
        self.dst.clear()
        self.set_status("비웠습니다.")

    def _on_send(self) -> None:
        out = self.dst.toPlainText()
        if not out:
            self.set_status("보낼 결과가 없습니다.", error=True)
            return
        if self._on_send_to_command is None:
            return
        self._on_send_to_command(out)
        self.set_status("결과를 명령 입력창으로 보냈습니다.")
