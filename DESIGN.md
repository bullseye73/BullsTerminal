# bullsTerminal — 설계 문서

SSH로 연결한 단일 타겟에 **기능별로 구성한 명령어를 일괄 실행**하는 우분투 데스크톱 GUI 앱.

---

## 1. 기술 스택 (확정)

| 항목 | 선택 | 비고 |
|------|------|------|
| 언어 | Python 3.10+ | 우분투 22.04/24.04 기본 |
| GUI | **PySide6 (Qt6)** | 공식 LGPL, `pip install PySide6` |
| SSH | **Paramiko** | 순수 Python, 세밀한 제어 |
| 설정/명령 저장 | **YAML** (`PyYAML`) | 사람이 읽기 쉬움, 앱 내 편집 병행 |
| 인증 | 비밀번호 (host/port/user/password) | 시작 시 다이얼로그 입력 |
| 패키징(선택) | PyInstaller / .deb | 배포 단계에서 결정 |

> 개발은 Samba 드라이브(`Z:`)에서 진행하되, 실행 타겟은 우분투. Python 코드라 크로스플랫폼 문제 없음. 파일 개행은 LF로 통일(`.editorconfig` 권장).

---

## 2. 화면(UX) 설계

### 2-1. 시작 시 — 연결 다이얼로그 (모달)
```
┌──────────── SSH 연결 ────────────┐
│  Host      [ 192.168.0.10      ] │
│  Port      [ 22 ]                │
│  Username  [ bullseye          ] │
│  Password  [ ••••••••          ] │
│  □ 이 세션 동안 비밀번호 기억     │
│                                  │
│         [ 연결 ]   [ 취소 ]      │
└──────────────────────────────────┘
```
- 연결 성공해야 메인 윈도우 진입. 실패 시 에러 메시지 표시 후 재입력.
- 비밀번호는 메모리에만 보관(디스크 저장 안 함). "기억"은 세션 한정.

### 2-2. 메인 윈도우 (3-Pane 레이아웃)
```
┌─────────────────────────────────────────────────────────────┐
│ [연결됨: bullseye@192.168.0.10]   [재연결] [연결끊기]  ●녹색  │  ← 상태바(상단)
├───────────────┬─────────────────────────────────────────────┤
│ 명령 그룹      │  선택된 그룹의 명령 목록                     │
│ (기능별)       │  ┌─────────────────────────────────────┐   │
│               │  │ ☑ 1. 서비스 상태 확인                 │   │
│ ▸ 시스템 점검  │  │ ☑ 2. 디스크 용량 확인                 │   │
│ ▸ 서비스 관리  │  │ ☐ 3. 로그 tail                       │   │
│ ▸ 배포         │  │ ☑ 4. nginx 재시작                    │   │
│ ▸ 로그 수집    │  │       [+ 명령 추가] [편집] [삭제]     │   │
│               │  └─────────────────────────────────────┘   │
│ [+그룹][편집]  │  [ ▶ 선택 실행 ]  [ ▶▶ 그룹 전체 실행 ]   │
├───────────────┴─────────────────────────────────────────────┤
│ 실행 결과 (콘솔/터미널 뷰)                                    │
│ $ systemctl status nginx                                     │
│ ● nginx.service - A high performance web server ...         │
│ ✔ exit 0  (0.4s)                                            │
│ ─────────────────────────────────────────                   │
│ $ df -h                                                      │
│ ...                                          [클리어][저장]  │
└─────────────────────────────────────────────────────────────┘
```

### 2-3. "기능별 구성"의 핵심 UX
- **좌측 트리 = 기능 그룹**: 예) `시스템 점검`, `서비스 관리`, `배포`, `로그 수집`.
- **우측 리스트 = 그룹 내 명령어**: 각 항목에 체크박스 → 원하는 것만 골라 **일괄 실행**.
- **두 가지 실행 버튼**:
  - `선택 실행`: 체크된 명령만 위→아래 순서로 순차 실행.
  - `그룹 전체 실행`: 그룹의 모든 명령 순차 실행.
- **명령 항목 속성**: 이름(라벨) / 실제 command / 설명(툴팁) / `실패 시 중단` 여부 / 확인 프롬프트(위험 명령용).
- **앱 내 편집**: `+명령 추가`/`편집`/`삭제`, 그룹 추가/이름변경/순서변경(드래그). 변경 즉시 YAML 파일에 저장.

---

## 3. 데이터 모델 (명령 저장 포맷)

`~/.config/bullsTerminal/commands.yaml` (앱 내 편집 + 직접 편집 모두 가능)

```yaml
groups:
  - name: "시스템 점검"
    commands:
      - label: "서비스 상태 확인"
        command: "systemctl status nginx --no-pager"
        description: "nginx 서비스 상태"
        stop_on_error: false
        confirm: false
      - label: "디스크 용량 확인"
        command: "df -h"
      - label: "메모리 확인"
        command: "free -m"
  - name: "서비스 관리"
    commands:
      - label: "nginx 재시작"
        command: "sudo systemctl restart nginx"
        confirm: true          # 실행 전 확인창
        stop_on_error: true
```

- 연결 프로필(선택): `~/.config/bullsTerminal/profiles.yaml`에 host/port/user만 저장(비밀번호 제외)해 재입력 편의 제공 — 2차 개선 항목.

---

## 4. 아키텍처 (모듈 구조)

```
bullsTerminal/
├── main.py                  # 진입점: QApplication → 연결 다이얼로그 → 메인 윈도우
├── ssh/
│   ├── client.py            # Paramiko 래퍼: connect, exec_command, 스트리밍 출력
│   └── runner.py            # 명령 큐 순차 실행, stop_on_error 처리
├── ui/
│   ├── connect_dialog.py    # 연결 입력 다이얼로그
│   ├── main_window.py       # 3-pane 메인
│   ├── group_tree.py        # 좌측 기능 그룹 트리
│   ├── command_list.py      # 우측 명령 리스트(체크박스)
│   ├── command_editor.py    # 명령 추가/편집 다이얼로그
│   └── console_view.py      # 하단 결과 콘솔
├── core/
│   ├── models.py            # Group / Command 데이터클래스
│   └── store.py             # commands.yaml 로드/저장
├── requirements.txt         # PySide6, paramiko, PyYAML
└── DESIGN.md
```

### 스레딩 설계 (중요)
- SSH I/O는 **QThread(워커)** 에서 실행. UI 스레드 블로킹 금지.
- 워커 → UI 통신은 **Qt Signal**로: `line_received(str)`, `command_finished(idx, exit_code, elapsed)`, `all_finished()`.
- 실행 중 `중지` 버튼 → 워커 취소 플래그 + 채널 close.

### 실행 흐름
1. 연결 다이얼로그 → Paramiko `SSHClient.connect()` (비밀번호).
2. 선택된 Command 리스트를 `runner`에 전달.
3. 워커가 순차로 `exec_command` → stdout/stderr 스트리밍을 Signal로 콘솔에 실시간 출력.
4. `stop_on_error=true`이고 exit code≠0 이면 중단, 아니면 다음 명령.
5. 완료 시 요약(성공 N / 실패 M).

---

## 5. 우분투 실행 방법

```bash
sudo apt install python3-venv python3-pip -y
cd /path/to/bullsTerminal       # (Samba 공유 위치)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```
> 원격 X 없이 우분투 데스크톱에서 직접 실행. 헤드리스 서버라면 X11 forwarding 또는 데스크톱 세션 필요.

---

## 6. 개발 로드맵 (단계)

1. **뼈대**: 프로젝트 구조 + `requirements.txt` + 빈 윈도우 뜨기.
2. **연결**: connect_dialog + Paramiko 연결 성공/실패 처리.
3. **명령 모델/저장**: models + store(YAML 로드·저장), 샘플 commands.yaml.
4. **UI 조립**: 그룹 트리 + 명령 리스트(체크박스) + 콘솔 뷰 배치.
5. **실행 엔진**: QThread runner + Signal 스트리밍 출력 + stop_on_error.
6. **편집 기능**: 그룹/명령 CRUD, 드래그 정렬, confirm 다이얼로그.
7. **마감**: 재연결/연결끊기, 결과 저장, 에러 UX, 아이콘/스타일.

---

## 7. 검토 사항 · 리스크

- **비밀번호 보관**: 메모리만. 디스크 저장 안 함(요구사항 부합). 화면엔 마스킹.
- **sudo 명령**: 이번 범위는 "비밀번호 인증"만 선택됨. `sudo` 명령을 넣으면 sudo 비번 프롬프트 처리가 별도 필요 → 초기엔 `sudo -n`(NOPASSWD 전제) 또는 `sudo`가 pty에서 비번 요구 시 대응 로직 필요. **추후 확장 포인트로 표시**.
- **장시간 명령**(예: `tail -f`): 무한 스트리밍은 `중지` 버튼으로 종료. 기본은 완료형 명령 가정.
- **문자 인코딩**: UTF-8 가정. 원격 로케일 다르면 깨질 수 있어 디코딩 `errors="replace"`.
- **단일 타겟 → 다중 타겟 확장**: models/runner를 타겟 리스트 기준으로 일반화하면 확장 가능하도록 인터페이스만 열어둠.

---

## 8. 다음 액션

승인 시 로드맵 1~3단계(뼈대·연결·저장)부터 구현 착수. 진행 여부를 알려주세요.
