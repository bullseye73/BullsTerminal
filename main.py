"""bullsTerminal 진입점.

메인 윈도우를 띄우고, 시작 시 첫 SSH 연결 다이얼로그로 터미널을 연다.
각 터미널 탭은 자신의 연결을 가지며 탭마다 다른 호스트로 연결할 수 있다.
"""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from core.resources import icon_paths
from ui.main_window import APP_NAME, MainWindow


def app_icon() -> QIcon:
    """ico(멀티 사이즈) + png 를 합쳐 모든 크기에서 선명한 아이콘을 만든다."""
    icon = QIcon()
    for path in icon_paths():
        icon.addFile(path)
    return icon


def _set_windows_app_id() -> None:
    """윈도우 작업표시줄에서 python.exe 가 아닌 앱 아이콘이 보이도록 AppUserModelID 지정."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("bullsTerminal")
    except Exception:
        pass


def main() -> int:
    _set_windows_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setDesktopFileName("bullsTerminal")  # 리눅스: .desktop 매칭(작업표시줄 아이콘)
    app.setWindowIcon(app_icon())

    window = MainWindow()
    window.show()
    window.open_initial_terminal()  # 첫 연결 다이얼로그
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
