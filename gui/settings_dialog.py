"""Application Settings dialog.

Tabs:
  Appearance — theme, color palette, row height, font size
  Behaviour  — timestamp decimal places, snap bookmarks to span edges
"""

from PySide6 import QtCore, QtWidgets

from .constants import PALETTES
from .theme import THEME, THEMES, _ICONS, dialog_base_qss, primary_button_qss, spinbox_qss


class SettingsDialog(QtWidgets.QDialog):
    """Tabbed settings dialog.

    Signals:
        theme_changed(str)       — user confirmed a different theme
        settings_applied(dict)   — user confirmed any settings change;
                                   dict keys: palette, row_height, font_size,
                                              ts_decimals, bookmark_snap
    """

    theme_changed    = QtCore.Signal(str)
    settings_applied = QtCore.Signal(dict)

    def __init__(self, current_theme: str, current_settings: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setModal(True)
        self.setStyleSheet(dialog_base_qss())
        self._current_theme   = current_theme
        self._selected_theme  = current_theme
        s = current_settings or {}

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._tabs = QtWidgets.QTabWidget()
        self._tabs.addTab(self._build_appearance_tab(s), "Appearance")
        self._tabs.addTab(self._build_behaviour_tab(s),  "Behaviour")
        outer.addWidget(self._tabs, 1)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        outer.addWidget(sep)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(16, 10, 16, 14)
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        for label, slot, is_default in [
            ("Apply",  self._on_apply,  False),
            ("OK",     self._on_ok,     True),
            ("Cancel", self.reject,     False),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setMinimumWidth(88)
            btn.setDefault(is_default)
            if is_default:
                btn.setStyleSheet(primary_button_qss())
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)

        outer.addLayout(btn_row)
        self.adjustSize()

    # ── Tab builders ─────────────────────────────────────────────────

    def _build_appearance_tab(self, s: dict) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
        )
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)

        # Theme
        self._theme_combo = QtWidgets.QComboBox()
        self._theme_combo.setMinimumWidth(180)
        for name in THEMES:
            self._theme_combo.addItem(name)
        idx = self._theme_combo.findText(self._current_theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentTextChanged.connect(self._on_theme_selected)
        form.addRow("Theme:", self._theme_combo)

        # Color palette
        self._palette_combo = QtWidgets.QComboBox()
        self._palette_combo.setMinimumWidth(180)
        for name in PALETTES:
            self._palette_combo.addItem(name)
        saved_palette = s.get("palette", "Default")
        pidx = self._palette_combo.findText(saved_palette)
        if pidx >= 0:
            self._palette_combo.setCurrentIndex(pidx)
        form.addRow("Color palette:", self._palette_combo)

        self._refresh_combo_qss()  # apply chevron QSS to both combos

        # Row height
        self._row_height_spin = QtWidgets.QDoubleSpinBox()
        self._row_height_spin.setRange(0.3, 1.0)
        self._row_height_spin.setSingleStep(0.05)
        self._row_height_spin.setDecimals(2)
        self._row_height_spin.setValue(s.get("row_height", 0.85))
        self._row_height_spin.setStyleSheet(spinbox_qss("QDoubleSpinBox"))
        self._row_height_spin.setToolTip(
            "Height of each function bar (data units). "
            "Smaller values show more rows simultaneously."
        )
        form.addRow("Row height:", self._row_height_spin)

        # Font size
        self._font_size_spin = QtWidgets.QSpinBox()
        self._font_size_spin.setRange(6, 14)
        self._font_size_spin.setValue(s.get("font_size", 8))
        self._font_size_spin.setStyleSheet(spinbox_qss("QSpinBox"))
        self._font_size_spin.setToolTip(
            "Point size for bar labels and bookmark labels on the chart."
        )
        form.addRow("Chart font size:", self._font_size_spin)

        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _build_behaviour_tab(self, s: dict) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
        )
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)

        # Timestamp decimal places
        self._ts_decimals_spin = QtWidgets.QSpinBox()
        self._ts_decimals_spin.setRange(0, 6)
        self._ts_decimals_spin.setValue(s.get("ts_decimals", 3))
        self._ts_decimals_spin.setStyleSheet(spinbox_qss("QSpinBox"))
        self._ts_decimals_spin.setToolTip(
            "Decimal places shown in the toolbar Jump/Window spinboxes "
            "and the bookmark time column."
        )
        form.addRow("Timestamp decimals:", self._ts_decimals_spin)

        # Snap bookmarks — 1×1 QTableWidget (checkbox only) + QLabel beside it.
        # The table gives the same checkbox indicator as SummaryDock/BookmarkDock;
        # the label stays a normal themed label, not a table cell.
        self._snap_table = QtWidgets.QTableWidget(1, 1)
        self._snap_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._snap_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        self._snap_table.horizontalHeader().setVisible(False)
        self._snap_table.verticalHeader().setVisible(False)
        self._snap_table.setShowGrid(False)
        self._snap_table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._snap_table.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        # Make cell and table background transparent so no box appears around
        # the indicator — it floats directly on the dialog background.
        self._snap_table.setStyleSheet(
            "QTableWidget { background: transparent; border: none; }"
            "QTableWidget::item { background: transparent; border: none; }"
        )
        row_h = self._snap_table.verticalHeader().defaultSectionSize()
        self._snap_table.setFixedSize(row_h + 4, row_h + 4)
        self._snap_table.setColumnWidth(0, row_h)

        self._snap_item = QtWidgets.QTableWidgetItem()
        self._snap_item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsUserCheckable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
        )
        self._snap_item.setCheckState(
            QtCore.Qt.CheckState.Checked
            if s.get("bookmark_snap", False)
            else QtCore.Qt.CheckState.Unchecked
        )
        self._snap_table.setItem(0, 0, self._snap_item)

        snap_label = QtWidgets.QLabel("Snap to nearest span start/end")
        snap_label.setToolTip(
            "When adding a bookmark via right-click or pick mode, "
            "snap the timestamp to the nearest span edge."
        )

        snap_row = QtWidgets.QWidget()
        snap_row_layout = QtWidgets.QHBoxLayout(snap_row)
        snap_row_layout.setContentsMargins(0, 0, 0, 0)
        snap_row_layout.setSpacing(6)
        snap_row_layout.addWidget(self._snap_table, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        snap_row_layout.addWidget(snap_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        snap_row_layout.addStretch()

        form.addRow("Bookmark snap:", snap_row)

        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    # ── Internal slots ───────────────────────────────────────────────

    def _combo_qss(self) -> str:
        _cd = (_ICONS / "chevron_dn.svg").as_posix()
        return (
            f"QComboBox::drop-down {{"
            f"  subcontrol-origin: border; subcontrol-position: right center;"
            f"  width: 18px; background: {THEME['bg_raised']};"
            f"  border-left: 1px solid {THEME['border_normal']}; border-radius: 0px 3px 3px 0px; }}"
            f"QComboBox::drop-down:hover {{ background: {THEME['interactive_hover_btn']}; }}"
            f"QComboBox::down-arrow {{ image: url({_cd}); width: 7px; height: 5px; }}"
        )

    def _refresh_combo_qss(self):
        qss = self._combo_qss()
        self._theme_combo.setStyleSheet(qss)
        self._palette_combo.setStyleSheet(qss)

    def _on_theme_selected(self, name: str):
        self._selected_theme = name

    def _collect_settings(self) -> dict:
        return {
            "palette":       self._palette_combo.currentText(),
            "row_height":    self._row_height_spin.value(),
            "font_size":     self._font_size_spin.value(),
            "ts_decimals":   self._ts_decimals_spin.value(),
            "bookmark_snap": self._snap_item.checkState() == QtCore.Qt.CheckState.Checked,
        }

    def _on_apply(self):
        if self._selected_theme and self._selected_theme != self._current_theme:
            self._current_theme = self._selected_theme
            self.theme_changed.emit(self._selected_theme)
            self._refresh_combo_qss()
        self.settings_applied.emit(self._collect_settings())

    def _on_ok(self):
        self._on_apply()
        self.accept()
