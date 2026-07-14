"""명령 그룹 저장소: ~/.config/rsCommand/commands.yaml 로드/저장."""
from __future__ import annotations

import os
from typing import List

import yaml

from core.models import Command, Group

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "rsCommand")
COMMANDS_PATH = os.path.join(CONFIG_DIR, "commands.yaml")


def _default_groups() -> List[Group]:
    return [
        Group(
            name="시스템 점검",
            commands=[
                Command("호스트 정보", "uname -a", "커널/호스트 정보"),
                Command("가동 시간", "uptime"),
                Command("디스크 용량", "df -h", "파일시스템 사용량"),
                Command("메모리 확인", "free -m"),
                Command("CPU 부하 상위", "ps -eo pid,pcpu,pmem,comm --sort=-pcpu | head -n 10"),
            ],
        ),
        Group(
            name="서비스 관리",
            commands=[
                Command("nginx 상태", "systemctl status nginx --no-pager"),
                Command(
                    "nginx 재시작",
                    "sudo systemctl restart nginx",
                    "주의: 서비스 재시작",
                    stop_on_error=True,
                    confirm=True,
                ),
            ],
        ),
        Group(
            name="로그 수집",
            commands=[
                Command("최근 시스템 로그", "journalctl -n 50 --no-pager"),
                Command("nginx 에러 로그", "sudo tail -n 50 /var/log/nginx/error.log"),
            ],
        ),
    ]


def load_groups() -> List[Group]:
    """설정 파일을 로드. 없으면 기본값을 만들어 저장 후 반환."""
    if not os.path.exists(COMMANDS_PATH):
        groups = _default_groups()
        save_groups(groups)
        return groups
    try:
        with open(COMMANDS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        raw = data.get("groups") or []
        return [Group.from_dict(g) for g in raw]
    except Exception:
        # 손상 시 백업 후 기본값으로 복구
        try:
            os.replace(COMMANDS_PATH, COMMANDS_PATH + ".bak")
        except OSError:
            pass
        groups = _default_groups()
        save_groups(groups)
        return groups


def save_groups(groups: List[Group]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = {"groups": [g.to_dict() for g in groups]}
    tmp = COMMANDS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, COMMANDS_PATH)
