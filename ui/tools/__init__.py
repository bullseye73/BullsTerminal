"""도구 레지스트리 — `도구` 메뉴와 도구 도크의 탭을 이 목록 하나로 관리한다.

도구는 두 종류다.

  * **내장 도구**: 클립보드 기록, 파일(SFTP) 처럼 메인 윈도우가 직접 만드는 위젯.
    `factory=None` 으로 두고 MainWindow 가 `register_builtin()` 으로 위젯을 넘긴다.
  * **패널 도구**: `TextUtilPanel` 을 상속한 변환기(Base64, 암호화 …).
    `factory` 만 등록하면 처음 켤 때 지연 생성된다.

새 패널 도구를 추가하려면 두 가지만 하면 된다.

    1) `ui/tools/<이름>_panel.py` 에 `TextUtilPanel` 을 상속한 패널을 만든다.
       (입력/결과 칸, 붙여넣기·복사·입력창으로·결과→입력 버튼, 상태줄은 상속으로 해결)
    2) 아래 `TOOL_SPECS` 에 `ToolSpec` 한 줄을 추가한다.

메뉴 항목 생성, 탭 추가/삭제, 폰트 적용, 명령 입력창 연동은 MainWindow 가
이 레지스트리를 보고 자동으로 처리하므로 메인 윈도우를 고칠 필요가 없다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from PySide6.QtWidgets import QWidget

from ui.tools.base64_panel import Base64Panel
from ui.tools.base_panel import TextUtilPanel
from ui.tools.crypto_panel import CryptoPanel

# 내장 도구 식별자 (MainWindow 가 위젯을 제공)
CLIPBOARD = "clipboard"
FILES = "files"


@dataclass(frozen=True)
class ToolSpec:
    """도구 하나의 메뉴/탭 정의."""

    key: str                                       # 내부 식별자
    title: str                                     # 메뉴 항목 이름(긴 이름)
    tab: str                                       # 도크 탭 이름(짧은 이름)
    factory: Optional[Callable[..., QWidget]] = None  # None = 내장 도구
    tooltip: str = ""
    default_on: bool = False                       # 시작할 때 탭으로 열어 둘지


TOOL_SPECS: Tuple[ToolSpec, ...] = (
    ToolSpec(
        key=CLIPBOARD,
        title="클립보드 기록",
        tab="클립보드",
        tooltip="복사한 셸 명령을 모아 보고 바로 실행",
        default_on=True,
    ),
    ToolSpec(
        key=FILES,
        title="파일 (SFTP)",
        tab="파일",
        tooltip="리모트 ↔ 로컬 파일 전송/관리",
        default_on=True,
    ),
    ToolSpec(
        key="base64",
        title="Base64 인코딩/디코딩",
        tab="Base64",
        factory=Base64Panel,
        tooltip="문자열 ↔ Base64 변환 (URL-safe 지원)",
    ),
    ToolSpec(
        key="crypto",
        title="암호화/복호화 (AES-256-GCM)",
        tab="암호화",
        factory=CryptoPanel,
        tooltip="비밀번호로 문자열을 암호화/복호화 (scrypt + AES-256-GCM)",
    ),
)

__all__ = [
    "CLIPBOARD",
    "FILES",
    "TOOL_SPECS",
    "Base64Panel",
    "CryptoPanel",
    "TextUtilPanel",
    "ToolSpec",
]
