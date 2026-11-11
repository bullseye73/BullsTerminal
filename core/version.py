"""앱 버전 관리 모듈.

기본 버전(DEFAULT_VERSION)을 정의하며:
- 소스 실행 시 Git 태그(예: v1.0.0)가 있으면 우선 참조하고, 없으면 DEFAULT_VERSION을 사용한다.
- CI/릴리스 빌드 시 `python core/version.py --set <version>` 명령으로 DEFAULT_VERSION을
  태그 버전과 동기화한 뒤 PyInstaller로 패키징한다.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

DEFAULT_VERSION = "1.0.3"


def normalize_version(raw: str) -> str:
    """'v1.0.0' 또는 '1.0.0' 형태의 문자열에서 선행 'v'를 제거해 정규화한다."""
    v = raw.strip()
    if v.lower().startswith("v"):
        v = v[1:].strip()
    return v or DEFAULT_VERSION


def _git_tag_version() -> str | None:
    """로컬 Git 저장소에서 현재 커밋 또는 가장 최근 태그 버전을 조회한다."""
    if getattr(sys, "frozen", False):
        return None
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        # HEAD 에서 도달 가능한 가장 가까운 v*.*.* 태그(HEAD 에 태그가 있으면 그 태그).
        # 앱 시작(임포트) 시 UI 스레드에서 실행되므로 호출 1회·짧은 타임아웃으로 제한.
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*.*.*"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        ).strip()
        if out:
            return normalize_version(out)
    except Exception:
        pass
    return None


def get_app_version() -> str:
    """현재 앱 버전을 반환한다 (예: '1.0.0')."""
    env_ver = os.environ.get("BULLSTERMINAL_VERSION", "").strip()
    if env_ver:
        return normalize_version(env_ver)
    git_ver = _git_tag_version()
    if git_ver:
        return git_ver
    return normalize_version(DEFAULT_VERSION)


APP_VERSION: str = get_app_version()


def _set_default_version_in_file(new_version: str) -> str:
    """이 파일(core/version.py)의 DEFAULT_VERSION 상수를 지정한 버전으로 갱신한다."""
    norm = normalize_version(new_version)
    path = os.path.abspath(__file__)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    updated = re.sub(
        r'^DEFAULT_VERSION\s*=\s*"[^"]*"',
        f'DEFAULT_VERSION = "{norm}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    return norm


def main() -> int:
    parser = argparse.ArgumentParser(description="bullsTerminal 버전 조회 및 설정 도구")
    parser.add_argument(
        "--set",
        dest="set_version",
        metavar="VERSION",
        help="DEFAULT_VERSION 값을 지정한 버전(예: 1.0.0 또는 v1.0.0)으로 업데이트",
    )
    args = parser.parse_args()
    if args.set_version:
        norm = _set_default_version_in_file(args.set_version)
        print(norm)
        return 0
    print(get_app_version())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

