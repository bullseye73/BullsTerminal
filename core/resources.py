"""번들(PyInstaller)/소스 실행 양쪽에서 동작하는 리소스 경로 해석."""
from __future__ import annotations

import os
import sys

# 소스 실행 시 프로젝트 루트, onefile 실행 시 임시 해제 폴더(sys._MEIPASS)
_BASE = getattr(sys, "_MEIPASS", None) or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


def resource_path(*parts: str) -> str:
    """번들 여부와 무관하게 리소스 파일의 절대 경로를 돌려준다."""
    return os.path.join(_BASE, *parts)


def icon_paths() -> "list[str]":
    """존재하는 앱 아이콘 파일 경로 목록(ico 는 멀티 사이즈라 우선)."""
    out = []
    for name in ("bullsterminal.ico", "bullsterminal.png"):
        p = resource_path("assets", name)
        if os.path.exists(p):
            out.append(p)
    return out
