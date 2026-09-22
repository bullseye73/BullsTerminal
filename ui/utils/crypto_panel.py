"""유틸: 비밀번호 기반 문자열 암호화 / 복호화 (AES-256-GCM).

출력은 한 줄 텍스트라 그대로 복사해 두거나 파일에 붙여 넣을 수 있다.

    bT1:<base64( salt(16) || nonce(12) || ciphertext+tag )>

키는 비밀번호에서 scrypt(N=2^14, r=8, p=1)로 유도하며, 소금(salt)과 논스(nonce)는
매번 새로 뽑는다. 따라서 같은 내용을 같은 비밀번호로 암호화해도 결과가 매번 다르다.
비밀번호는 메모리에만 있고 어디에도 저장되지 않는다(잊으면 복구 불가).
"""
from __future__ import annotations

import base64
import os
from typing import List

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from ui.utils.base64_panel import b64_to_bytes
from ui.utils.base_panel import TextUtilPanel

try:  # cryptography 는 paramiko 의 의존성이라 보통 함께 설치된다.
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover - 설치 환경에 따라
    CRYPTO_AVAILABLE = False

PREFIX = "bT1:"          # 형식 식별자(버전 포함)
_SALT_LEN = 16
_NONCE_LEN = 12
_KEY_LEN = 32            # AES-256
_SCRYPT_N = 2 ** 14      # 약 16MB / 수십 ms
_SCRYPT_R = 8
_SCRYPT_P = 1


def _require_crypto() -> None:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "cryptography 패키지가 없어 암호화를 쓸 수 없습니다. "
            "pip install -r requirements.txt 로 설치하세요."
        )


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(password.encode("utf-8"))


def encrypt_text(plain: str, password: str) -> str:
    """문자열을 비밀번호로 암호화해 `bT1:...` 한 줄로 돌려준다."""
    _require_crypto()
    if not plain:
        raise ValueError("암호화할 내용이 없습니다.")
    if not password:
        raise ValueError("비밀번호를 입력하세요.")
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    blob = AESGCM(_derive_key(password, salt)).encrypt(
        nonce, plain.encode("utf-8"), None
    )
    return PREFIX + base64.b64encode(salt + nonce + blob).decode("ascii")


def decrypt_text(token: str, password: str) -> str:
    """`bT1:...` 형식(접두사 없어도 허용)을 비밀번호로 복호화."""
    _require_crypto()
    if not password:
        raise ValueError("비밀번호를 입력하세요.")
    body = "".join(token.split())
    if not body:
        raise ValueError("복호화할 내용이 없습니다.")
    if body.lower().startswith(PREFIX.lower()):
        body = body[len(PREFIX):]

    raw = b64_to_bytes(body)  # 공백·패딩 누락 허용
    if len(raw) <= _SALT_LEN + _NONCE_LEN:
        raise ValueError("암호문 형식이 올바르지 않습니다(길이 부족).")
    salt = raw[:_SALT_LEN]
    nonce = raw[_SALT_LEN:_SALT_LEN + _NONCE_LEN]
    blob = raw[_SALT_LEN + _NONCE_LEN:]

    try:
        plain = AESGCM(_derive_key(password, salt)).decrypt(nonce, blob, None)
    except InvalidTag:
        raise ValueError(
            "복호화 실패 — 비밀번호가 다르거나 내용이 손상되었습니다."
        ) from None
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return plain.decode("utf-8", errors="backslashreplace")


class CryptoPanel(TextUtilPanel):
    """비밀번호 기반 암호화/복호화 패널."""

    INPUT_HINT = "암호화할 문자열 또는 복호화할 bT1:... 암호문을 입력/붙여넣기"
    START_HINT = "비밀번호를 넣고 [🔒 암호화] 또는 [🔓 복호화]를 누르세요."

    def action_rows(self) -> List[QHBoxLayout]:
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("비밀번호 (저장되지 않음)")
        self.password.setToolTip(
            "이 비밀번호로 키를 만듭니다(scrypt + AES-256-GCM).\n"
            "어디에도 저장되지 않으므로 잊으면 복구할 수 없습니다."
        )
        self.password.returnPressed.connect(self._on_encrypt)
        show = QCheckBox("표시")
        show.setToolTip("비밀번호를 화면에 보이기")
        show.toggled.connect(
            lambda on: self.password.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )

        pw_row = QHBoxLayout()
        pw_row.addWidget(QLabel("비밀번호"))
        pw_row.addWidget(self.password, 1)
        pw_row.addWidget(show)

        enc_btn = QPushButton("🔒 암호화")
        enc_btn.setToolTip("입력 문자열 → AES-256-GCM 암호문 (bT1:...)")
        enc_btn.clicked.connect(self._on_encrypt)
        dec_btn = QPushButton("🔓 복호화")
        dec_btn.setToolTip("bT1:... 암호문 → 원래 문자열")
        dec_btn.clicked.connect(self._on_decrypt)
        if not CRYPTO_AVAILABLE:
            for b in (enc_btn, dec_btn):
                b.setEnabled(False)
                b.setToolTip("cryptography 패키지가 설치되어 있지 않습니다.")

        act_row = QHBoxLayout()
        act_row.addWidget(enc_btn, 1)
        act_row.addWidget(dec_btn, 1)
        return [pw_row, act_row]

    # -------------------------------------------------------------- 동작들
    def _on_encrypt(self) -> None:
        try:
            out = encrypt_text(self.source_text(), self.password.text())
        except (ValueError, RuntimeError) as exc:
            self.set_status(str(exc), error=True)
            return
        self.set_result(out)
        self.set_status(
            f"암호화 완료 — {len(out)}자 (AES-256-GCM). "
            "비밀번호를 잊으면 복구할 수 없습니다."
        )

    def _on_decrypt(self) -> None:
        try:
            out = decrypt_text(self.source_text(), self.password.text())
        except (ValueError, RuntimeError) as exc:
            self.dst.clear()
            self.set_status(str(exc), error=True)
            return
        self.set_result(out)
        self.set_status(f"복호화 완료 — {len(out)}자")
