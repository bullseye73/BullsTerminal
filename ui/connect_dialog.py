"""SSH 연결 정보 입력 모달 다이얼로그 (즐겨찾기 선택/저장 포함)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core import store
from ssh.client import ConnectionInfo


class ConnectDialog(QDialog):
    def __init__(self, parent=None, prefill: ConnectionInfo | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSH 연결")
        self.setModal(True)
        self.setMinimumWidth(400)

        self._favorites = store.load_favorites()

        # 즐겨찾기 선택 행
        self.fav_combo = QComboBox()
        self.fav_combo.addItem("— 즐겨찾기 선택 —", None)
        for fav in self._favorites:
            self.fav_combo.addItem(fav["name"], fav)
        self.fav_combo.currentIndexChanged.connect(self._on_fav_selected)
        fav_save = QPushButton("저장")
        fav_del = QPushButton("삭제")
        fav_save.setToolTip("현재 입력을 즐겨찾기에 저장")
        fav_del.setToolTip("선택한 즐겨찾기 삭제")
        fav_save.clicked.connect(self._on_fav_save)
        fav_del.clicked.connect(self._on_fav_delete)
        fav_row = QHBoxLayout()
        fav_row.addWidget(self.fav_combo, 1)
        fav_row.addWidget(fav_save)
        fav_row.addWidget(fav_del)

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
        form.addRow("즐겨찾기", fav_row)
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

    # --------------------------------------------------------- 즐겨찾기
    def _on_fav_selected(self, index: int) -> None:
        fav = self.fav_combo.itemData(index)
        if not fav:
            return
        self.host_edit.setText(fav.get("host", ""))
        self.port_spin.setValue(int(fav.get("port", 22) or 22))
        self.user_edit.setText(fav.get("username", ""))
        self.pass_edit.setText(fav.get("password", ""))

    def _reload_fav_combo(self, select_name: str | None = None) -> None:
        self._favorites = store.load_favorites()
        self.fav_combo.blockSignals(True)
        self.fav_combo.clear()
        self.fav_combo.addItem("— 즐겨찾기 선택 —", None)
        target = 0
        for i, fav in enumerate(self._favorites, start=1):
            self.fav_combo.addItem(fav["name"], fav)
            if select_name and fav["name"] == select_name:
                target = i
        self.fav_combo.setCurrentIndex(target)
        self.fav_combo.blockSignals(False)

    def _on_fav_save(self) -> None:
        host = self.host_edit.text().strip()
        user = self.user_edit.text().strip()
        if not host or not user:
            QMessageBox.information(self, "안내", "Host 와 Username 을 먼저 입력하세요.")
            return
        default_name = self.fav_combo.currentText()
        if not default_name or default_name.startswith("—"):
            default_name = f"{user}@{host}"
        name, ok = QInputDialog.getText(
            self, "즐겨찾기 저장", "이름:", text=default_name
        )
        name = name.strip()
        if not ok or not name:
            return

        store_pw = ""
        if self.pass_edit.text():
            if QMessageBox.question(
                self,
                "비밀번호 저장",
                "비밀번호도 함께 저장할까요?\n(평문으로 저장됩니다. 저장하지 않으면 연결 시 입력)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) == QMessageBox.Yes:
                store_pw = self.pass_edit.text()

        entry = {
            "name": name,
            "host": host,
            "port": self.port_spin.value(),
            "username": user,
            "password": store_pw,
        }
        favs = store.load_favorites()
        favs = [f for f in favs if f["name"] != name]  # 같은 이름은 교체
        favs.append(entry)
        favs.sort(key=lambda f: f["name"].lower())
        store.save_favorites(favs)
        self._reload_fav_combo(select_name=name)

    def _on_fav_delete(self) -> None:
        fav = self.fav_combo.currentData()
        if not fav:
            QMessageBox.information(self, "안내", "삭제할 즐겨찾기를 선택하세요.")
            return
        if QMessageBox.question(
            self, "즐겨찾기 삭제", f"'{fav['name']}' 을(를) 삭제할까요?"
        ) != QMessageBox.Yes:
            return
        favs = [f for f in store.load_favorites() if f["name"] != fav["name"]]
        store.save_favorites(favs)
        self._reload_fav_combo()

    # --------------------------------------------------------- 연결
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
