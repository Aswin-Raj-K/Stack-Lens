"""Dialog for establishing a live J-Link connection from the GUI."""

import pathlib

from PySide6 import QtCore, QtWidgets

_ICONS = pathlib.Path(__file__).parent / "icons"


class ConnectJLinkDialog(QtWidgets.QDialog):
    def __init__(self, elf_path="", device="AMA4B2KP-KBR", cpu_mhz=96.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect to J-Link")
        self.setModal(True)
        self.resize(520, 210)

        # Match toolbar visual style: muted labels, brighter input/button borders.
        self.setStyleSheet(
            "QLabel { color: #7878a0; }"
            "QLineEdit, QDoubleSpinBox { border-color: #505068; }"
            "QPushButton { border-color: #505068; }"
        )

        layout = QtWidgets.QFormLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setLabelAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        # ELF path row (line-edit + Browse button)
        elf_row = QtWidgets.QHBoxLayout()
        elf_row.setSpacing(6)
        self._elf_edit = QtWidgets.QLineEdit(elf_path or "")
        self._elf_edit.setPlaceholderText("Path to .elf / .axf file \u2026")
        browse_btn = QtWidgets.QPushButton("Browse\u2026")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_elf)
        elf_row.addWidget(self._elf_edit)
        elf_row.addWidget(browse_btn)
        layout.addRow("ELF file:", elf_row)

        # Device
        self._device_edit = QtWidgets.QLineEdit(device)
        layout.addRow("Device:", self._device_edit)

        # CPU MHz — modern chevron step buttons
        self._mhz_spin = QtWidgets.QDoubleSpinBox()
        self._mhz_spin.setRange(1.0, 2000.0)
        self._mhz_spin.setDecimals(1)
        self._mhz_spin.setSuffix(" MHz")
        self._mhz_spin.setValue(cpu_mhz)
        _cu = (_ICONS / "chevron_up.svg").as_posix()
        _cd = (_ICONS / "chevron_dn.svg").as_posix()
        self._mhz_spin.setStyleSheet(
            "QDoubleSpinBox::up-button {"
            "  subcontrol-origin: border; subcontrol-position: right top;"
            "  width: 18px; background: #22222c;"
            "  border-left: 1px solid #3a3a4a; border-top-right-radius: 3px; }"
            "QDoubleSpinBox::down-button {"
            "  subcontrol-origin: border; subcontrol-position: right bottom;"
            "  width: 18px; background: #22222c;"
            "  border-left: 1px solid #3a3a4a; border-top: 1px solid #3a3a4a;"
            "  border-bottom-right-radius: 3px; }"
            "QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {"
            "  background: #2e2e3e; }"
            "QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed {"
            "  background: #1a1a26; }"
            f"QDoubleSpinBox::up-arrow {{ image: url({_cu}); width: 7px; height: 5px; }}"
            f"QDoubleSpinBox::down-arrow {{ image: url({_cd}); width: 7px; height: 5px; }}"
        )
        layout.addRow("CPU clock:", self._mhz_spin)

        # OK / Cancel — accent the primary action button
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ok_btn = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setStyleSheet(
                "QPushButton { background: #1e3a5a; border: 1px solid #3870a8;"
                "  color: #c8e0ff; padding: 4px 16px; border-radius: 3px; }"
                "QPushButton:hover { background: #25487a; border-color: #5090c8; }"
                "QPushButton:pressed { background: #142840; }"
            )
        layout.addRow(btns)

    def _browse_elf(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select ELF file", "", "ELF / AXF (*.elf *.axf);;All Files (*)"
        )
        if path:
            self._elf_edit.setText(path)

    def get_params(self):
        """Return (elf_path, device, cpu_mhz)."""
        return (
            self._elf_edit.text().strip(),
            self._device_edit.text().strip(),
            self._mhz_spin.value(),
        )
