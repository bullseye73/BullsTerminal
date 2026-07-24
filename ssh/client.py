"""Paramiko 기반 SSH 클라이언트 래퍼 (비밀번호 인증).

먼저 표준(기본) 알고리즘으로 접속을 시도하고(최신 서버의 rsa-sha2 등 정상 협상),
실패하면 레거시 호스트키(ssh-rsa/ssh-dss)·SHA-1 키교환을 후순위로 추가해 재시도한다
(구형 서버/장비 대응). 표준 시도를 먼저 하므로 최신 서버 협상을 방해하지 않는다.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass

import paramiko

# 구형 서버 호환용으로 추가할 호스트키 알고리즘(후순위)
_EXTRA_HOST_KEYS = ("rsa-sha2-512", "rsa-sha2-256", "ssh-rsa", "ssh-dss")
# 구형 서버 호환용 키교환 알고리즘(있으면 추가)
_EXTRA_KEX = (
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group1-sha1",
    "diffie-hellman-group-exchange-sha1",
)


@dataclass
class ConnectionInfo:
    host: str
    port: int
    username: str
    password: str  # 메모리에만 보관, 디스크 저장 안 함


def _extend(seq, extras):
    result = list(seq)
    for item in extras:
        if item not in result:
            result.append(item)
    return tuple(result)


class SSHClient:
    def __init__(self) -> None:
        self._transport: paramiko.Transport | None = None
        self.info: ConnectionInfo | None = None

    def connect(self, info: ConnectionInfo, timeout: float = 10.0) -> None:
        first_error: Exception | None = None
        # 1) 표준(기본) 알고리즘으로 먼저 시도 — 최신 서버(rsa-sha2 등) 정상 협상
        try:
            self._transport = self._open(info, timeout, legacy=False)
            self.info = info
            return
        except paramiko.AuthenticationException:
            raise  # 비밀번호 오류는 재시도하지 않음
        except Exception as exc:
            first_error = exc

        # 2) 실패 시 레거시 알고리즘(ssh-rsa/ssh-dss, SHA-1 kex)으로 재시도 — 구형 서버 대응
        try:
            self._transport = self._open(info, timeout, legacy=True)
            self.info = info
        except paramiko.AuthenticationException:
            raise
        except Exception:
            raise first_error  # 대표(첫) 오류를 표시

    def _open(
        self, info: ConnectionInfo, timeout: float, legacy: bool
    ) -> paramiko.Transport:
        sock = socket.create_connection((info.host, info.port), timeout=timeout)
        transport = paramiko.Transport(sock)

        if legacy:
            # 구형 서버 호환: 레거시 호스트키/키교환을 후순위로 추가
            try:
                transport._preferred_keys = _extend(
                    transport._preferred_keys, _EXTRA_HOST_KEYS
                )
                transport._preferred_kex = _extend(
                    transport._preferred_kex, _EXTRA_KEX
                )
            except Exception:
                pass

        try:
            transport.start_client(timeout=timeout)
            transport.auth_password(info.username, info.password)
        except Exception:
            transport.close()
            raise

        if not transport.is_authenticated():
            transport.close()
            raise RuntimeError("인증에 실패했습니다. 사용자명/비밀번호를 확인하세요.")
        return transport

    def is_connected(self) -> bool:
        return self._transport is not None and self._transport.is_active()

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
