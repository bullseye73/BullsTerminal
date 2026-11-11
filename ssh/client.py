"""Paramiko 기반 SSH 클라이언트 래퍼 (비밀번호 인증).

- 서버 호스트키를 known_hosts 와 대조한 뒤에만 비밀번호를 보낸다(중간자 공격 방지).
  처음 보는 서버/키가 바뀐 서버는 verify 콜백으로 사용자에게 확인받는다.
- 먼저 표준(기본) 알고리즘으로 접속하고, **알고리즘 협상 실패(IncompatiblePeer)일 때만**
  레거시 알고리즘을 후순위로 덧붙여 재시도한다(구형 서버/장비 대응).
  타임아웃 등 다른 오류로는 약한 알고리즘으로 내려가지 않는다.
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import paramiko
from paramiko.ssh_exception import IncompatiblePeer

from core.store import CONFIG_DIR, ensure_private_dir, open_private

KNOWN_HOSTS_PATH = os.path.join(CONFIG_DIR, "known_hosts")
_SYSTEM_KNOWN_HOSTS = os.path.join(os.path.expanduser("~"), ".ssh", "known_hosts")
_KNOWN_HOSTS_LOCK = threading.Lock()

# verify(host, port, key_type, fingerprint, status) -> 신뢰 여부
#   status: "new"(처음 보는 서버) | "changed"(저장된 키와 다름)
HostKeyVerifier = Callable[[str, int, str, str, str], bool]


class HostKeyRejected(Exception):
    """호스트키를 신뢰하지 않아 연결을 중단."""


class ConnectCancelled(Exception):
    """사용자가 연결을 취소."""


@dataclass
class ConnectionInfo:
    host: str
    port: int
    username: str
    password: str  # 메모리에만 보관, 디스크 저장 안 함


def _host_id(host: str, port: int) -> str:
    """known_hosts 표기(OpenSSH 규칙): 22 번이 아니면 [host]:port."""
    return host if port == 22 else f"[{host}]:{port}"


def fingerprint(key: paramiko.PKey) -> str:
    """OpenSSH 와 같은 형식의 SHA256 지문."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _load_host_keys(path: str) -> paramiko.HostKeys:
    keys = paramiko.HostKeys()
    try:
        if os.path.isfile(path):
            keys.load(path)
    except Exception:
        pass  # 손상된 파일은 '모르는 서버'로 취급(사용자 확인을 다시 받음)
    return keys


def _known_status(host: str, port: int, key: paramiko.PKey) -> str:
    """'ok' | 'new' | 'changed'. 앱 저장소 우선, 없으면 ~/.ssh/known_hosts 참조."""
    hid = _host_id(host, port)
    status = "new"
    for path in (KNOWN_HOSTS_PATH, _SYSTEM_KNOWN_HOSTS):
        entry = _load_host_keys(path).lookup(hid)
        if not entry:
            continue
        saved = entry.get(key.get_name())
        if saved is not None and saved.asbytes() == key.asbytes():
            return "ok"
        status = "changed"  # 같은 호스트에 다른 키(또는 다른 종류의 키)만 저장돼 있음
        if path == KNOWN_HOSTS_PATH:
            break  # 앱이 직접 저장한 기록이 우선
    return status


def _remember_host_key(host: str, port: int, key: paramiko.PKey) -> None:
    """확인된 호스트키를 앱 known_hosts 에 저장(같은 호스트의 이전 키는 교체)."""
    hid = _host_id(host, port)
    with _KNOWN_HOSTS_LOCK:
        keys = _load_host_keys(KNOWN_HOSTS_PATH)
        while keys.lookup(hid):  # __delitem__ 은 한 줄씩만 지움
            try:
                del keys[hid]
            except KeyError:
                break
        keys.add(hid, key.get_name(), key)
        ensure_private_dir()
        tmp = KNOWN_HOSTS_PATH + ".tmp"
        with open_private(tmp) as f:
            for host_entry in keys._entries:  # HostKeys.save 와 동일(권한만 0600)
                line = host_entry.to_line()
                if line:
                    f.write(line)
        os.replace(tmp, KNOWN_HOSTS_PATH)


def _append_legacy_algorithms(transport: paramiko.Transport) -> None:
    """기본 우선순위는 그대로 두고, 지원 가능한 나머지 알고리즘을 뒤에 덧붙인다.

    안전한 알고리즘이 항상 먼저 협상되고, 구형 서버/장비가 레거시만 제공할 때에만
    뒤쪽 항목이 선택된다.
    """
    for pref, info in (
        ("_preferred_keys", "_key_info"),
        ("_preferred_kex", "_kex_info"),
        ("_preferred_ciphers", "_cipher_info"),
        ("_preferred_macs", "_mac_info"),
    ):
        try:
            table = getattr(transport, info, None)
            current = tuple(getattr(transport, pref, ()) or ())
            if table:
                extra = tuple(k for k in table.keys() if k not in current)
                setattr(transport, pref, current + extra)
        except Exception:
            pass


class SSHClient:
    def __init__(self) -> None:
        self._transport: paramiko.Transport | None = None
        self.info: ConnectionInfo | None = None
        self.legacy_used = False  # 레거시 알고리즘 재시도로 연결되었는지
        self._cancelled = False
        self._pending_sock: Optional[socket.socket] = None
        self._pending_transport: Optional[paramiko.Transport] = None

    def cancel(self) -> None:
        """진행 중인 connect() 를 다른 스레드에서 중단(소켓을 닫아 즉시 깨움)."""
        self._cancelled = True
        for obj in (self._pending_transport, self._pending_sock):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass

    def connect(
        self,
        info: ConnectionInfo,
        timeout: float = 10.0,
        verify: Optional[HostKeyVerifier] = None,
    ) -> None:
        # 1) 표준(기본) 알고리즘으로 먼저 시도 — 최신 서버(rsa-sha2 등) 정상 협상
        try:
            self._transport = self._open(info, timeout, verify, legacy=False)
        except IncompatiblePeer:
            if self._cancelled:
                raise ConnectCancelled("연결이 취소되었습니다.") from None
            # 2) 알고리즘 협상 실패일 때만 레거시를 덧붙여 재시도 — 구형 서버/장비 대응
            self._transport = self._open(info, timeout, verify, legacy=True)
            self.legacy_used = True
        self.info = info

    def _open(
        self,
        info: ConnectionInfo,
        timeout: float,
        verify: Optional[HostKeyVerifier],
        legacy: bool,
    ) -> paramiko.Transport:
        try:
            return self._open_inner(info, timeout, verify, legacy)
        except (HostKeyRejected, ConnectCancelled):
            raise
        except Exception:
            if self._cancelled:
                raise ConnectCancelled("연결이 취소되었습니다.") from None
            raise
        finally:
            self._pending_sock = None
            self._pending_transport = None

    def _open_inner(
        self,
        info: ConnectionInfo,
        timeout: float,
        verify: Optional[HostKeyVerifier],
        legacy: bool,
    ) -> paramiko.Transport:
        if self._cancelled:
            raise ConnectCancelled("연결이 취소되었습니다.")
        sock = socket.create_connection((info.host, info.port), timeout=timeout)
        self._pending_sock = sock
        transport = paramiko.Transport(sock)
        self._pending_transport = transport
        transport.auth_timeout = max(timeout, 15.0)  # 인증 응답 무한 대기 방지

        if legacy:
            _append_legacy_algorithms(transport)

        try:
            transport.start_client(timeout=timeout)
            # 비밀번호를 보내기 전에 반드시 서버 신원(호스트키)부터 확인한다.
            self._check_host_key(info, transport, verify)
            if self._cancelled:
                raise ConnectCancelled("연결이 취소되었습니다.")
            transport.auth_password(info.username, info.password)
        except Exception:
            transport.close()
            raise

        if not transport.is_authenticated():
            transport.close()
            raise RuntimeError("인증에 실패했습니다. 사용자명/비밀번호를 확인하세요.")

        # 연결 유지 + 죽은 연결 감지 (30초 간격 keepalive)
        try:
            transport.set_keepalive(30)
        except Exception:
            pass
        return transport

    @staticmethod
    def _check_host_key(
        info: ConnectionInfo,
        transport: paramiko.Transport,
        verify: Optional[HostKeyVerifier],
    ) -> None:
        key = transport.get_remote_server_key()
        status = _known_status(info.host, info.port, key)
        if status == "ok":
            return
        fp = fingerprint(key)
        trusted = bool(
            verify and verify(info.host, info.port, key.get_name(), fp, status)
        )
        if not trusted:
            raise HostKeyRejected(
                "서버 호스트키를 신뢰하지 않아 연결을 중단했습니다.\n"
                f"{key.get_name()} {fp}"
            )
        try:
            _remember_host_key(info.host, info.port, key)
        except Exception:
            pass  # 저장 실패 시 다음 접속 때 다시 확인받음

    def is_connected(self) -> bool:
        return self._transport is not None and self._transport.is_active()

    def get_transport(self) -> "paramiko.Transport | None":
        return self._transport

    def _require_transport(self) -> paramiko.Transport:
        if self._transport is None or not self._transport.is_active():
            raise RuntimeError("연결되지 않았습니다.")
        return self._transport

    def open_channel(self, command: str, pty: bool = False) -> paramiko.Channel:
        """명령을 실행할 새 채널을 연다. 호출자가 recv/close 를 담당."""
        channel = self._require_transport().open_session()
        if pty:
            channel.get_pty()
        channel.exec_command(command)
        return channel

    def open_shell(
        self, term: str = "xterm-256color", width: int = 80, height: int = 24
    ) -> paramiko.Channel:
        """대화형 셸 채널을 연다 (터미널 탭용). 같은 연결 위에 여러 개 가능."""
        channel = self._require_transport().open_session()
        channel.get_pty(term=term, width=width, height=height)
        channel.invoke_shell()
        return channel

    def close(self) -> None:
        if self._transport is not None:
            try:
                self._transport.close()
            finally:
                self._transport = None
