"""rsCommand 진입점.

메인 윈도우를 띄우고, 시작 시 첫 SSH 연결 다이얼로그로 터미널을 연다.
각 터미널 탭은 자신의 연결을 가지며 탭마다 다른 호스트로 연결할 수 있다.
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("rsCommand")

    window = MainWindow()
    window.show()
    window.open_initial_terminal()  # 첫 연결 다이얼로그
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
