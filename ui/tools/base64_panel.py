"""도구: Base64 인코딩 / 디코딩."""
from __future__ import annotations

import base64
import binascii
from typing import List

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QWidget

from ui.tools.base_panel import TextUtilPanel

# 디코딩 시 허용할 문자(표준 + URL-safe 알파벳, 패딩 포함)
_B64_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/-_="
)


def encode_base64(text: str, url_safe: bool = False) -> str:
    """문자열을 UTF-8 로 인코딩한 뒤 Base64 문자열로 변환."""
    raw = text.encode("utf-8")
    out = base64.urlsafe_b64encode(raw) if url_safe else base64.b64encode(raw)
    return out.decode("ascii")


def b64_to_bytes(text: str) -> bytes:
    """관대한 Base64 → bytes 변환 (다른 도구에서도 재사용).

    공백/줄바꿈은 무시하고, URL-safe(`-_`) 알파벳과 빠진 패딩(`=`)도 받아들인다.
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
        return base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Base64 디코딩 실패: {exc}") from exc


def decode_base64(text: str) -> "tuple[str, bool]":
    """Base64 문자열을 디코딩.

    반환값은 (디코딩 결과, UTF-8 로 온전히 해석됐는지 여부).
    UTF-8 이 아니면 깨진 바이트를 `\\xNN` 로 표시해 돌려준다.
    """
    raw = b64_to_bytes(text)
    try:
        return raw.decode("utf-8"), True
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="backslashreplace"), False


class Base64Panel(TextUtilPanel):
    """Base64 인코딩/디코딩 패널."""

    INPUT_HINT = "인코딩할 문자열 또는 디코딩할 Base64 를 입력/붙여넣기"
    START_HINT = "문자열을 입력하고 [▼ 인코딩] 또는 [▲ 디코딩]을 누르세요."

    def action_rows(self) -> List[QHBoxLayout]:
        enc_btn = QPushButton("▼ 인코딩")
        enc_btn.setToolTip("입력 문자열 → Base64 (UTF-8 기준)")
        enc_btn.clicked.connect(self._on_encode)
        dec_btn = QPushButton("▲ 디코딩")
        dec_btn.setToolTip("입력 Base64 → 문자열 (공백/줄바꿈·패딩 누락 허용)")
        dec_btn.clicked.connect(self._on_decode)

        row = QHBoxLayout()
        row.addWidget(enc_btn, 1)
        row.addWidget(dec_btn, 1)
        return [row]

    def option_widgets(self) -> List[QWidget]:
        self.url_safe = QCheckBox("URL-safe")
        self.url_safe.setToolTip(
            "인코딩 결과에 +/ 대신 -_ 사용 (JWT·URL 파라미터용).\n"
            "디코딩은 두 방식 모두 자동으로 인식합니다."
        )
        return [self.url_safe]

    # -------------------------------------------------------------- 동작들
    def _on_encode(self) -> None:
        text = self.source_text()
        if not text:
            self.set_status("입력이 비어 있습니다.", error=True)
            return
        out = encode_base64(text, url_safe=self.url_safe.isChecked())
        self.set_result(out)
        kind = "URL-safe Base64" if self.url_safe.isChecked() else "Base64"
        self.set_status(
            f"인코딩 완료 — 입력 {len(text.encode('utf-8'))}바이트 → {kind} {len(out)}자"
        )

    def _on_decode(self) -> None:
        try:
            out, is_utf8 = decode_base64(self.source_text())
        except ValueError as exc:
            self.dst.clear()
            self.set_status(str(exc), error=True)
            return
        self.set_result(out)
        if is_utf8:
            self.set_status(f"디코딩 완료 — {len(out)}자")
        else:
            self.set_status(
                "디코딩했지만 UTF-8 텍스트가 아닙니다. 깨진 바이트는 \\xNN 로 표시했습니다.",
                error=True,
            )
