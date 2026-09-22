"""유틸 모음 — `유틸` 메뉴에서 켜고 끄는 독립 도크 패널들.

새 유틸을 추가하려면 두 가지만 하면 된다.

    1) `ui/utils/<이름>_panel.py` 에 `TextUtilPanel` 을 상속한 패널을 만든다.
       (입력/결과 칸, 붙여넣기·복사·입력창으로·결과→입력 버튼, 상태줄은 상속으로 해결)
    2) 아래 `UTIL_SPECS` 에 `UtilSpec` 한 줄을 추가한다.

메뉴 항목 생성, 도크 생성/해제, 폰트 적용, 명령 입력창 연동은 MainWindow 가
이 레지스트리를 보고 자동으로 처리하므로 메인 윈도우를 고칠 필요가 없다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDockWidget, QWidget

from ui.utils.base64_panel import Base64Panel
from ui.utils.base_panel import TextUtilPanel
from ui.utils.crypto_panel import CryptoPanel


@dataclass(frozen=True)
class UtilSpec:
    """유틸 하나의 메뉴/도크 정의."""

    key: str                              # 내부 식별자(도크 objectName)
    title: str                            # 메뉴 항목 = 도크 제목
    factory: Callable[..., TextUtilPanel]  # (on_send_to_command=, parent=) 를 받는 패널 생성자
    tooltip: str = ""
    shortcut: str = ""                    # 기본은 비움 — 아래 주석 참고


# 단축키를 기본으로 비워 둔 이유: 메뉴 단축키는 창 전체에서 가로채이므로
# 터미널로 가야 할 키 조합을 빼앗는다. 꼭 필요하면 여기에만 지정하면 된다.
UTIL_SPECS: Tuple[UtilSpec, ...] = (
    UtilSpec(
        key="base64",
        title="Base64 인코딩/디코딩",
        factory=Base64Panel,
        tooltip="문자열 ↔ Base64 변환 (URL-safe 지원)",
    ),
    UtilSpec(
        key="crypto",
        title="암호화/복호화 (AES-256-GCM)",
        factory=CryptoPanel,
        tooltip="비밀번호로 문자열을 암호화/복호화 (scrypt + AES-256-GCM)",
    ),
)


class UtilDock(QDockWidget):
    """닫기(✕)를 알려 주는 도크 — 메뉴 체크 상태와 동기화하기 위해 사용."""

    closed = Signal(str)

    def __init__(self, key: str, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        self._key = key
        self.setObjectName(f"utilDock_{key}")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt 규약)
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit(self._key)
