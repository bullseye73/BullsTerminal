"""데이터 모델: 기능 그룹(Group)과 그 안의 명령(Command)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

# 명령으로서 실행되는 sudo 만 감지(행 시작 또는 쉘 구분자 ; && || | ( 뒤).
# `grep sudo` 처럼 인자로 등장하는 sudo(앞에 일반 공백만 있는 경우)는 제외한다.
# `sudo -n`(무비번 전제)은 비밀번호 입력이 필요 없으므로 제외.
_SUDO_RE = re.compile(r"(?:^|[\n;&|(])\s*sudo(?:\s|$)")
_SUDO_NONINTERACTIVE_RE = re.compile(
    r"(?:^|[\n;&|(])\s*sudo\s+(?:-n\b|--non-interactive\b)"
)


def command_uses_sudo(command: str) -> bool:
    if _SUDO_NONINTERACTIVE_RE.search(command):
        return False
    return bool(_SUDO_RE.search(command))


@dataclass
class Command:
    label: str
    command: str
    description: str = ""
    stop_on_error: bool = False
    confirm: bool = False
    sudo: bool = False  # 명시적 sudo 표시(자동 감지와 별개로 강제)

    @staticmethod
    def from_dict(d: dict) -> "Command":
        return Command(
            label=str(d.get("label", "")).strip(),
            command=str(d.get("command", "")),
            description=str(d.get("description", "")),
            stop_on_error=bool(d.get("stop_on_error", False)),
            confirm=bool(d.get("confirm", False)),
            sudo=bool(d.get("sudo", False)),
        )

    def to_dict(self) -> dict:
        out = {"label": self.label, "command": self.command}
        if self.description:
            out["description"] = self.description
        if self.stop_on_error:
            out["stop_on_error"] = True
        if self.confirm:
            out["confirm"] = True
        if self.sudo:
            out["sudo"] = True
        return out

    def needs_sudo_password(self) -> bool:
        """PTY + 비밀번호 자동입력이 필요한 명령인지."""
        return self.sudo or command_uses_sudo(self.command)


@dataclass
class Group:
    name: str
    commands: List[Command] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> "Group":
        cmds = [Command.from_dict(c) for c in (d.get("commands") or [])]
        return Group(name=str(d.get("name", "")).strip(), commands=cmds)

    def to_dict(self) -> dict:
        return {"name": self.name, "commands": [c.to_dict() for c in self.commands]}
