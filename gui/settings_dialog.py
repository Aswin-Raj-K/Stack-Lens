"""Application Settings dialog.

Currently exposes one tab: Appearance (theme selection).
Add new QWidget tabs to the tab widget in __init__ for future settings.
"""

from PySide6 import QtCore, QtWidgets

from .theme import THEME, THEMES, _ICONS


class SettingsDialog(QtWidgets.QDialog):
    """Tabbed settings dialog.

    Signals:
        theme_changed(str) — emitted when the user confirms a different theme
                             (on Apply or OK, not immediately on list selection)
    """

    theme_changed = QtCore.Signal(str)

    def __init__(self, current_theme: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(480, 320)
        self._current_theme = current_theme
        self._selected_theme = current_theme

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Tab widget — add new tabs here for future settings categories
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.addTab(self._build_appearance_tab(), "Appearance")
        outer.addWidget(self._tabs, 1)

        # Separator
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        outer.addWidget(sep)

        # Button row
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(16, 10, 16, 14)
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        for label, slot, is_default in [
            ("Apply", self._on_apply, False),
            ("OK", self._on_ok, True),
            ("Cancel", self.reject, False),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setMinimumWidth(88)
            btn.setDefault(is_default)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)

        outer.addLayout(btn_row)

    # ── Tab builders ────────────────────────────────────────────────

    def _build_appearance_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)

        self._theme_combo = QtWidgets.QComboBox()
        self._theme_combo.setMinimumWidth(180)
        for name in THEMES:
            self._theme_combo.addItem(name)
        idx = self._theme_combo.findText(self._current_theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentTextChanged.connect(self._on_theme_selected)
        self._refresh_combo_qss()

        form.addRow("Theme:", self._theme_combo)
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    # ── Internal slots ──────────────────────────────────────────────

    def _refresh_combo_qss(self):
        """Reapply the combo drop-down arrow QSS from the current THEME."""
        _cd = (_ICONS / "chevron_dn.svg").as_posix()
        self._theme_combo.setStyleSheet(
            f"QComboBox::drop-down {{"
            f"  subcontrol-origin: border; subcontrol-position: right center;"
            f"  width: 18px; background: {THEME['bg_raised']};"
            f"  border-left: 1px solid {THEME['border_normal']}; border-radius: 0px 3px 3px 0px; }}"
            f"QComboBox::drop-down:hover {{ background: {THEME['interactive_hover_btn']}; }}"
            f"QComboBox::down-arrow {{ image: url({_cd}); width: 7px; height: 5px; }}"
        )

    def _on_theme_selected(self, name: str):
        self._selected_theme = name

    def _on_apply(self):
        if self._selected_theme and self._selected_theme != self._current_theme:
            self._current_theme = self._selected_theme
            self.theme_changed.emit(self._selected_theme)
            # emit() is synchronous — apply_theme() has run by here, so THEME
            # now holds the new values and the combo QSS will be correct.
            self._refresh_combo_qss()

    def _on_ok(self):
        self._on_apply()
        self.accept()
