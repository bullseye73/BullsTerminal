"""명령 입력창용 bash/셸 구문 강조기 (QSyntaxHighlighter)."""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

_KEYWORDS = (
    "if|then|else|elif|fi|for|while|until|do|done|case|esac|in|function|select|"
    "time|return|break|continue|local|export|source|alias|set|unset|readonly|"
    "declare|eval|exec|trap|echo|cd|pushd|popd|test"
)


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class BashHighlighter(QSyntaxHighlighter):
    """명령 첫 단어/키워드/변수/옵션/문자열/주석/연산자에 색을 입힌다."""

    def __init__(self, document) -> None:
        super().__init__(document)

        cmd = _fmt("#8ae234", bold=True)      # 명령 첫 단어 (초록)
        keyword = _fmt("#729fcf", bold=True)  # 셸 키워드 (파랑)
        number = _fmt("#e0a0ff")              # 숫자
        option = _fmt("#ad7fa8")              # -x / --long 옵션 (보라)
        variable = _fmt("#34e2e2")            # $VAR ${VAR} (청록)
        operator = _fmt("#fce94f")            # | & ; > < && || (노랑)
        comment = _fmt("#7f9f7f", italic=True)  # # 주석 (회록)
        string = _fmt("#e9b96e")              # "..." '...' (주황)

        # 순서 중요: 뒤 규칙이 겹치는 부분을 덮어씀.
        self._rules = [
            (QRegularExpression(r"(?:^|[;|&])\s*([A-Za-z_][\w./-]*)"), cmd, 1),
            (QRegularExpression(r"\b(?:" + _KEYWORDS + r")\b"), keyword, 0),
            (QRegularExpression(r"\b\d+\b"), number, 0),
            (QRegularExpression(r"(?:^|\s)(-{1,2}[A-Za-z0-9][\w-]*)"), option, 1),
            (QRegularExpression(r"\$(?:\{[^}]*\}|\w+|[@*#?$!0-9-])"), variable, 0),
            (QRegularExpression(r"&&|\|\||>>|2>&1|[|&;<>]"), operator, 0),
            (QRegularExpression(r"(?:^|\s)(#.*)$"), comment, 1),
            (QRegularExpression(r"'[^']*'"), string, 0),
            (QRegularExpression(r'"(?:\\.|[^"\\])*"'), string, 0),
        ]

    def highlightBlock(self, text: str) -> None:
        for rx, fmt, group in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                start = m.capturedStart(group)
                length = m.capturedLength(group)
                if length > 0:
                    self.setFormat(start, length, fmt)
