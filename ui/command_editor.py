"""명령 추가/편집 다이얼로그."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.models import Command


class CommandEditor(QDialog):
    def __init__(self, parent=None, command: Command | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("명령 편집" if command else "명령 추가")
        self.setModal(True)
        self.setMinimumWidth(460)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("예: nginx 재시작")
        self.command_edit = QPlainTextEdit()
        self.command_edit.setPlaceholderText("예: sudo systemctl restart nginx")
        self.command_edit.setMinimumHeight(80)
        self.desc_edit = QLineEdit()
        self.confirm_check = QCheckBox("실행 전 확인창 표시 (위험 명령)")

        if command is not None:
            self.label_edit.setText(command.label)
            self.command_edit.setPlainText(command.command)
            self.desc_edit.setText(command.description)
            self.confirm_check.setChecked(command.confirm)

        form = QFormLayout()
        form.addRow("이름", self.label_edit)
        form.addRow("명령", self.command_edit)
        form.addRow("설명", self.desc_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("확인")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.confirm_check)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.label_edit.text().strip():
            self.label_edit.setFocus()
            return
        if not self.command_edit.toPlainText().strip():
            self.command_edit.setFocus()
            return
        self.accept()

    def result_command(self) -> Command:
        return Command(
            label=self.label_edit.text().strip(),
            command=self.command_edit.toPlainText().strip(),
            description=self.desc_edit.text().strip(),
            confirm=self.confirm_check.isChecked(),
        )
