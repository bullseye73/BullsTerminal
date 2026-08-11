"""명령 그룹 저장소: ~/.config/rsCommand/commands.yaml 로드/저장."""
from __future__ import annotations

import os
from typing import List

import yaml

from core.models import Command, Group

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "rsCommand")
COMMANDS_PATH = os.path.join(CONFIG_DIR, "commands.yaml")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.yaml")
FAVORITES_PATH = os.path.join(CONFIG_DIR, "favorites.yaml")


def load_favorites() -> "list[dict]":
    """SSH 연결 즐겨찾기 목록 로드."""
    if not os.path.exists(FAVORITES_PATH):
        return []
    try:
        with open(FAVORITES_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return []
    out = []
    for d in (data.get("favorites") or []):
        name = str(d.get("name", "")).strip()
        host = str(d.get("host", "")).strip()
        if not name or not host:
            continue
        try:
            port = int(d.get("port", 22) or 22)
        except (TypeError, ValueError):
            port = 22
        out.append({
            "name": name,
            "host": host,
            "port": port,
            "username": str(d.get("username", "")),
            "password": str(d.get("password", "")),
        })
    return out


def _safe_port(value) -> int:
    try:
        return int(value or 22)
    except (TypeError, ValueError):
        return 22


def save_favorites(favs: "list[dict]") -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = {"favorites": [
        {
            "name": str(f.get("name", "")),
            "host": str(f.get("host", "")),
            "port": _safe_port(f.get("port", 22)),
            "username": str(f.get("username", "")),
            "password": str(f.get("password", "")),
        }
        for f in favs
    ]}
    tmp = FAVORITES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, FAVORITES_PATH)

# 기본 폰트: 기존 Monospace 에서 크기만 한 단계 크게(11 -> 12)
DEFAULT_SETTINGS = {"font_family": "Monospace", "font_size": 12}


def load_settings() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        family = str(data.get("font_family") or DEFAULT_SETTINGS["font_family"])
        size = int(data.get("font_size") or DEFAULT_SETTINGS["font_size"])
        if size <= 0:
            size = DEFAULT_SETTINGS["font_size"]
        return {"font_family": family, "font_size": size}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = {
        "font_family": str(settings.get("font_family", DEFAULT_SETTINGS["font_family"])),
        "font_size": int(settings.get("font_size", DEFAULT_SETTINGS["font_size"])),
    }
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, SETTINGS_PATH)


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


def export_groups(groups: List[Group], path: str) -> None:
    """명령 그룹을 지정한 파일로 백업(내보내기)."""
    data = {"groups": [g.to_dict() for g in groups]}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def import_groups(path: str) -> List[Group]:
    """백업 파일에서 명령 그룹을 읽어온다(가져오기)."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "groups" not in data:
        raise ValueError("올바른 rsCommand 명령 백업 파일이 아닙니다.")
    return [Group.from_dict(g) for g in (data.get("groups") or [])]
