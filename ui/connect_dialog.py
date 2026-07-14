"""시작 시 SSH 연결 정보를 입력받는 모달 다이얼로그."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ssh.client import ConnectionInfo


class ConnectDialog(QDialog):
    def __init__(self, parent=None, prefill: ConnectionInfo | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSH 연결")
        self.setModal(True)
        self.setMinimumWidth(360)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("예: 192.168.0.10")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.remember_check = QCheckBox("이 세션 동안 비밀번호 기억")
        self.remember_check.setChecked(True)

        if prefill is not None:
            self.host_edit.setText(prefill.host)
            self.port_spin.setValue(prefill.port)
            self.user_edit.setText(prefill.username)
            if prefill.password:
                self.pass_edit.setText(prefill.password)

        form = QFormLayout()
        form.addRow("Host", self.host_edit)
        form.addRow("Port", self.port_spin)
        form.addRow("Username", self.user_edit)
        form.addRow("Password", self.pass_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("연결")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.remember_check)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.host_edit.text().strip():
            self.host_edit.setFocus()
            return
        if not self.user_edit.text().strip():
            self.user_edit.setFocus()
            return
        self.accept()

    def connection_info(self) -> ConnectionInfo:
        return ConnectionInfo(
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            username=self.user_edit.text().strip(),
            password=self.pass_edit.text(),
        )

    def remember_password(self) -> bool:
        return self.remember_check.isChecked()
