"""bullsNote 스타일(Linear / Craft 다크 징크 + 블루 액센트) 글로벌 테마 및 스타일시트.

핵심 디자인 원칙:
1. 선(Border) 대신 패널 깊이감(Surface Depth) 차등 적용:
   - 사이드바/헤더: #121214
   - 리스트/패널/입력창: #18181b
   - 터미널/메인 캔버스: #141417
2. 영역 간 흰색/밝은 회색 구분선 제거:
   - QSplitter::handle 및 QMainWindow::separator를 평소에는 1px 미세 라인(#232329)으로 숨기고,
     마우스 호버 시에만 블루 액센트(#3b82f6)가 은은하게 드러나도록 처리.
3. 슬림 스크롤바, 라운드 리스트 카드, 저채도 상태 배지(.bn-subtle-tag 스타일) 적용.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# bullsNote 디자인 토큰
SURFACE_SIDEBAR = "#121214"
SURFACE_LIST = "#18181b"
SURFACE_CANVAS = "#141417"
SURFACE_ELEVATED = "#202024"
BORDER_SUBTLE = "#242429"
BORDER_HOVER = "#34343c"
TEXT_PRIMARY = "#f4f4f5"
TEXT_SECONDARY = "#e4e4e7"
TEXT_MUTED = "#a1a1aa"
TEXT_DIM = "#71717a"
ACCENT_BLUE = "#3b82f6"
ACCENT_BLUE_TEXT = "#93c5fd"


GLOBAL_STYLESHEET = f"""
/* ==========================================================================
   기본 윈도우 및 공통 위젯
   ========================================================================== */
QMainWindow, QDialog {{
    background-color: {SURFACE_SIDEBAR};
    color: {TEXT_SECONDARY};
}}

QWidget {{
    color: {TEXT_SECONDARY};
    selection-background-color: rgba(59, 130, 246, 0.28);
    selection-color: {TEXT_PRIMARY};
}}

/* 메인 윈도우 도크 구분선 (기존 흰색 세로 라인 제거) */
QMainWindow::separator {{
    background-color: {BORDER_SUBTLE};
    width: 1px;
    height: 1px;
    margin: 0px;
    padding: 0px;
}}
QMainWindow::separator:hover {{
    background-color: {ACCENT_BLUE};
}}

/* ==========================================================================
   스플리터 핸들 (bullsNote ResizeSplitter 스타일: 평소 미세선, 호버 시 블루)
   ========================================================================== */
QSplitter {{
    background: transparent;
    border: none;
}}

QSplitter::handle:horizontal {{
    background-color: transparent;
    border-left: 1px solid {BORDER_SUBTLE};
    width: 5px;
    margin: 0px 1px;
}}
QSplitter::handle:horizontal:hover {{
    background-color: rgba(59, 130, 246, 0.16);
    border-left: 1px solid {ACCENT_BLUE};
}}

QSplitter::handle:vertical {{
    background-color: transparent;
    border-top: 1px solid {BORDER_SUBTLE};
    height: 5px;
    margin: 2px 0px;
}}
QSplitter::handle:vertical:hover {{
    background-color: rgba(59, 130, 246, 0.16);
    border-top: 1px solid {ACCENT_BLUE};
}}

/* ==========================================================================
   메뉴바 / 컨텍스트 메뉴 / 툴팁 / 상태바
   ========================================================================== */
QMenuBar {{
    background-color: {SURFACE_SIDEBAR};
    color: {TEXT_SECONDARY};
    border-bottom: 1px solid {BORDER_SUBTLE};
    padding: 2px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 5px;
}}
QMenuBar::item:selected {{
    background-color: rgba(255, 255, 255, 0.07);
    color: {TEXT_PRIMARY};
}}

QMenu {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_HOVER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background-color: rgba(59, 130, 246, 0.22);
    color: {ACCENT_BLUE_TEXT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER_SUBTLE};
    margin: 4px 6px;
}}

QStatusBar {{
    background-color: {SURFACE_SIDEBAR};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER_SUBTLE};
    font-size: 12px;
}}

QToolTip {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_HOVER};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* ==========================================================================
   상단 통합 상태 헤더 & 섹션 타이틀
   ========================================================================== */
QWidget#topHeaderBar {{
    background-color: {SURFACE_SIDEBAR};
    border-bottom: 1px solid {BORDER_SUBTLE};
}}

QWidget#sidebarContainer {{
    background-color: {SURFACE_SIDEBAR};
}}

QWidget#centerContainer {{
    background-color: {SURFACE_CANVAS};
}}

QLabel#sectionTitle {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    padding: 2px 2px;
}}

QLabel#subtleHint {{
    color: {TEXT_DIM};
    font-size: 11px;
}}

QLabel#badgeCount {{
    background-color: rgba(59, 130, 246, 0.14);
    color: {ACCENT_BLUE_TEXT};
    border: 1px solid rgba(59, 130, 246, 0.24);
    border-radius: 5px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 600;
}}

/* ==========================================================================
   리스트 위젯 (bullsNote 사이드바 아이템 & 노트 카드 스타일)
   ========================================================================== */
QListWidget {{
    background-color: {SURFACE_LIST};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    color: {TEXT_SECONDARY};
    border-radius: 6px;
    padding: 6px 8px;
    margin: 1px 0px;
    border: 1px solid transparent;
}}

QListWidget::item:hover {{
    background-color: rgba(255, 255, 255, 0.05);
}}

QListWidget::item:selected {{
    background-color: rgba(59, 130, 246, 0.16);
    color: {ACCENT_BLUE_TEXT};
    border: 1px solid rgba(59, 130, 246, 0.28);
    font-weight: 600;
}}

/* ==========================================================================
   트리 위젯 (파일 브라우저) & 헤더
   ========================================================================== */
QTreeWidget {{
    background-color: {SURFACE_LIST};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    padding: 2px;
    outline: none;
    alternate-background-color: rgba(255, 255, 255, 0.015);
}}

QTreeWidget::item {{
    padding: 4px 6px;
    border-radius: 4px;
}}

QTreeWidget::item:hover {{
    background-color: rgba(255, 255, 255, 0.05);
}}

QTreeWidget::item:selected {{
    background-color: rgba(59, 130, 246, 0.18);
    color: {ACCENT_BLUE_TEXT};
}}

QHeaderView {{
    background-color: transparent;
    border: none;
}}

QHeaderView::section {{
    background-color: {SURFACE_LIST};
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid {BORDER_SUBTLE};
    border-right: 1px solid {BORDER_SUBTLE};
}}
QHeaderView::section:last {{
    border-right: none;
}}

/* ==========================================================================
   입력창 (QLineEdit / QPlainTextEdit / QComboBox / QSpinBox)
   ========================================================================== */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {SURFACE_LIST};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: rgba(59, 130, 246, 0.30);
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid rgba(59, 130, 246, 0.55);
    background-color: {SURFACE_ELEVATED};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_HOVER};
    border-radius: 6px;
    selection-background-color: rgba(59, 130, 246, 0.22);
    selection-color: {ACCENT_BLUE_TEXT};
    outline: none;
}}

QPlainTextEdit {{
    background-color: {SURFACE_LIST};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: rgba(59, 130, 246, 0.30);
}}

QPlainTextEdit:focus {{
    border: 1px solid rgba(59, 130, 246, 0.50);
}}

/* ==========================================================================
   버튼 (기본 / Subtle 컴팩트 / Primary 블루 액센트 / Danger)
   ========================================================================== */
QPushButton {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 6px;
    padding: 5px 11px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: #27272d;
    border-color: {BORDER_HOVER};
    color: {TEXT_PRIMARY};
}}

QPushButton:pressed {{
    background-color: #1c1c21;
}}

QPushButton:disabled {{
    background-color: rgba(255, 255, 255, 0.02);
    color: {TEXT_DIM};
    border-color: rgba(255, 255, 255, 0.04);
}}

/* 헤더 우측 컴팩트 버튼 (＋, 이름, 수정, 삭제) */
QPushButton[variant="subtle"] {{
    background-color: rgba(255, 255, 255, 0.03);
    color: {TEXT_MUTED};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 5px;
    padding: 3px 8px;
    font-size: 11px;
}}
QPushButton[variant="subtle"]:hover {{
    background-color: rgba(255, 255, 255, 0.08);
    color: {TEXT_PRIMARY};
    border-color: {BORDER_HOVER};
}}

/* 상단 툴바 아이콘 버튼 */
QPushButton[variant="icon"] {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
}}
QPushButton[variant="icon"]:hover {{
    background-color: rgba(255, 255, 255, 0.07);
    border-color: {BORDER_SUBTLE};
}}

/* Primary 액션 버튼 (▶ 선택, ▶▶ 그룹, 입력, 새 터미널 등) */
QPushButton[variant="primary"] {{
    background-color: rgba(59, 130, 246, 0.16);
    color: {ACCENT_BLUE_TEXT};
    border: 1px solid rgba(59, 130, 246, 0.32);
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background-color: rgba(59, 130, 246, 0.26);
    border-color: rgba(59, 130, 246, 0.50);
    color: #bfdbfe;
}}
QPushButton[variant="primary"]:pressed {{
    background-color: rgba(59, 130, 246, 0.34);
}}

/* 솔리드 블루 강조 버튼 */
QPushButton[variant="solid-primary"] {{
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #3b82f6;
    font-weight: 600;
}}
QPushButton[variant="solid-primary"]:hover {{
    background-color: #3b82f6;
    border-color: #60a5fa;
}}

/* ==========================================================================
   체크박스 (전체 선택, 옵션 체크박스, 리스트 아이템 체크박스)
   ========================================================================== */
QCheckBox {{
    color: {TEXT_MUTED};
    spacing: 6px;
}}
QCheckBox:hover {{
    color: {TEXT_PRIMARY};
}}
QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid #3f3f46;
    background-color: {SURFACE_SIDEBAR};
}}
QCheckBox::indicator:hover, QListWidget::indicator:hover, QTreeWidget::indicator:hover {{
    border-color: {ACCENT_BLUE};
}}
QCheckBox::indicator:checked, QListWidget::indicator:checked, QTreeWidget::indicator:checked {{
    background-color: #2563eb;
    border-color: {ACCENT_BLUE};
}}
QCheckBox::indicator:indeterminate {{
    background-color: rgba(59, 130, 246, 0.45);
    border-color: {ACCENT_BLUE};
}}

/* ==========================================================================
   탭 위젯 (터미널 탭 & 도구 도크 탭 — 밝은 회색 프레임 제거)
   ========================================================================== */
QTabWidget {{
    background: transparent;
    border: none;
}}

QTabWidget::pane {{
    background-color: {SURFACE_CANVAS};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    top: -1px;
}}

QTabWidget::tab-bar {{
    left: 0px;
}}

QTabBar {{
    background: transparent;
    qproperty-drawBase: 0;
}}

QTabBar::tab {{
    background-color: {SURFACE_SIDEBAR};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER_SUBTLE};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 14px;
    margin-right: 3px;
    font-weight: 500;
}}

QTabBar::tab:hover:!selected {{
    background-color: {SURFACE_LIST};
    color: {TEXT_SECONDARY};
}}

QTabBar::tab:selected {{
    background-color: {SURFACE_LIST};
    color: {TEXT_PRIMARY};
    border-color: {BORDER_SUBTLE};
    border-top: 2px solid {ACCENT_BLUE};
    font-weight: 600;
}}

/* ==========================================================================
   도크 위젯 (우측 도구 패널 — 상하단 흰색 테두리 완전 제거)
   ========================================================================== */
QDockWidget {{
    background-color: {SURFACE_SIDEBAR};
    color: {TEXT_SECONDARY};
    border: none;
}}

QDockWidget::title {{
    background-color: {SURFACE_SIDEBAR};
    color: {TEXT_MUTED};
    padding: 7px 10px;
    border-bottom: 1px solid {BORDER_SUBTLE};
    font-weight: 600;
    text-align: left;
}}

QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: rgba(255, 255, 255, 0.08);
}}

/* ==========================================================================
   슬림 스크롤바 (bullsNote 글로벌 슬림 스크롤바와 동일)
   ========================================================================== */
QScrollBar:vertical {{
    background: transparent;
    width: 7px;
    margin: 2px 1px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: rgba(161, 161, 170, 0.25);
    min-height: 24px;
    border-radius: 3px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba(161, 161, 170, 0.48);
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
    border: none;
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 7px;
    margin: 1px 2px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: rgba(161, 161, 170, 0.25);
    min-width: 24px;
    border-radius: 3px;
}}

QScrollBar::handle:horizontal:hover {{
    background: rgba(161, 161, 170, 0.48);
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
    border: none;
    width: 0px;
}}
"""


def apply_bullsnote_theme(app: QApplication) -> None:
    """QApplication에 Fusion 엔진 + bullsNote 다크 징크 팔레트 및 스타일시트를 적용한다."""
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(SURFACE_SIDEBAR))
    pal.setColor(QPalette.WindowText, QColor(TEXT_SECONDARY))
    pal.setColor(QPalette.Base, QColor(SURFACE_LIST))
    pal.setColor(QPalette.AlternateBase, QColor(SURFACE_ELEVATED))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE_ELEVATED))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.Text, QColor(TEXT_SECONDARY))
    pal.setColor(QPalette.Button, QColor(SURFACE_ELEVATED))
    pal.setColor(QPalette.ButtonText, QColor(TEXT_SECONDARY))
    pal.setColor(QPalette.BrightText, QColor("#ffffff"))
    pal.setColor(QPalette.Highlight, QColor("#2563eb"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_DIM))
    pal.setColor(QPalette.Mid, QColor(BORDER_SUBTLE))
    pal.setColor(QPalette.Dark, QColor(SURFACE_SIDEBAR))
    pal.setColor(QPalette.Light, QColor(BORDER_HOVER))
    app.setPalette(pal)

    app.setStyleSheet(GLOBAL_STYLESHEET)
