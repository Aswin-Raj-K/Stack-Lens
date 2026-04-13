"""Bookmark dock — save and recall named, depth-aware timeline points.

Each bookmark stores a timestamp, a depth (Y-axis row), and a visibility flag.
Visible bookmarks are rendered on the flame chart by FlameItem.
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .dock_base import DockBase
from .sort_helpers import SortableHeader, pad_columns_for_sort_indicator
from .theme import THEME, dialog_base_qss, primary_button_qss, spinbox_qss

_ROLE_IDX = QtCore.Qt.ItemDataRole.UserRole + 1   # index into self._bookmarks


class BookmarkDock(DockBase):
    """Dockable table of named, depth-aware timestamp bookmarks.

    Signals:
        activated(t_us)          — user clicked a name cell; jump to that time
        save_bookmark_requested  — "Pin" button clicked (main window provides t_us)
        pick_position_requested  — ⌖ button clicked; main window enters pick mode
        bookmarks_changed(list)  — emitted on any list or visibility change
    """

    activated               = QtCore.Signal(float)
    save_bookmark_requested = QtCore.Signal()
    pick_position_requested = QtCore.Signal()
    bookmarks_changed       = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__("Bookmarks", parent)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)

        self._bookmarks: list[dict] = []   # [{name, t_us, depth, visible}]
        self._updating  = False

        container = QtWidgets.QWidget()
        layout    = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Control strip ────────────────────────────────────────────
        ctrl = QtWidgets.QWidget()
        ctrl.setObjectName("DockCtrlPanel")
        ctrl_row = QtWidgets.QHBoxLayout(ctrl)
        ctrl_row.setContentsMargins(6, 5, 6, 5)
        ctrl_row.setSpacing(6)

        self._save_btn = QtWidgets.QPushButton("+ Pin current position")
        self._save_btn.setToolTip(
            "Save the centre of the current view as a named bookmark  (Ctrl+B)"
        )
        self._save_btn.clicked.connect(lambda: self.save_bookmark_requested.emit())
        ctrl_row.addWidget(self._save_btn, 1)

        self._pick_btn = QtWidgets.QToolButton()
        self._pick_btn.setText("\u2316")   # ⌖ TARGET / CROSSHAIR
        self._pick_btn.setToolTip(
            "Click a position on the chart to place a bookmark at that exact point"
        )
        self._pick_btn.setFixedSize(26, 26)
        self._pick_btn.clicked.connect(lambda: self.pick_position_requested.emit())
        ctrl_row.addWidget(self._pick_btn)

        layout.addWidget(ctrl)

        # ── Table ────────────────────────────────────────────────────
        self._table = QtWidgets.QTableWidget()
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setHorizontalHeader(SortableHeader(self._table))
        self._table.setSortingEnabled(False)   # no sorting needed for bookmarks
        header = self._table.horizontalHeader()
        header.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            ["Show", "Bookmark", f"Time ({self._unit_label})", "Depth"]
        )
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table, 1)

        self.setWidget(container)

    # ── Public API ───────────────────────────────────────────────────

    def load_bookmarks(self, bookmarks: list) -> None:
        """Populate from saved data (called on session restore)."""
        for bm in bookmarks:
            self._add_bookmark(
                bm["name"], bm["t_us"],
                bm.get("depth", 0),
                bm.get("visible", True),
            )

    def save_bookmark(self, t_us: float, depth: int = 0) -> None:
        """Show name+depth dialog then add the bookmark."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Pin Position")
        dlg.setModal(True)
        dlg.setMinimumWidth(320)
        dlg.setStyleSheet(dialog_base_qss())

        form = QtWidgets.QFormLayout(dlg)
        form.setSpacing(14)
        form.setContentsMargins(20, 20, 20, 16)
        form.setLabelAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        name_edit = QtWidgets.QLineEdit(f"@ {t_us / 1000:.3f} ms")
        name_edit.selectAll()
        form.addRow("Name:", name_edit)

        depth_spin = QtWidgets.QSpinBox()
        depth_spin.setRange(0, 64)
        depth_spin.setValue(depth)
        depth_spin.setStyleSheet(spinbox_qss("QSpinBox"))
        form.addRow("Depth:", depth_spin)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        ok_btn = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setStyleSheet(primary_button_qss())
        form.addRow(btns)

        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            return
        self._add_bookmark(name, t_us, depth_spin.value(), visible=True)
        self._persist()

    def get_bookmarks(self) -> list:
        return list(self._bookmarks)

    def set_unit(self, unit_label: str, unit_scale: float) -> None:
        super().set_unit(unit_label, unit_scale)
        # Update header
        self._table.setHorizontalHeaderLabels(
            ["Show", "Bookmark", f"Time ({unit_label})", "Depth"]
        )
        # Reformat time cells
        self._updating = True
        try:
            for row in range(self._table.rowCount()):
                time_item = self._table.item(row, 2)
                if time_item is None:
                    continue
                idx = time_item.data(_ROLE_IDX)
                if idx is not None and 0 <= idx < len(self._bookmarks):
                    t_us = self._bookmarks[idx]["t_us"]
                    time_item.setText(f"{t_us * unit_scale:.3f}")
        finally:
            self._updating = False

    # ── Internal ─────────────────────────────────────────────────────

    def _add_bookmark(self, name: str, t_us: float, depth: int,
                      visible: bool = True) -> None:
        bm = {"name": name, "t_us": t_us, "depth": depth, "visible": visible}
        self._bookmarks.append(bm)
        idx = len(self._bookmarks) - 1

        self._updating = True
        try:
            row = self._table.rowCount()
            self._table.setRowCount(row + 1)

            # Col 0 — Show checkbox
            show_item = QtWidgets.QTableWidgetItem()
            show_item.setFlags(
                QtCore.Qt.ItemFlag.ItemIsUserCheckable
                | QtCore.Qt.ItemFlag.ItemIsEnabled
            )
            show_item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if visible
                else QtCore.Qt.CheckState.Unchecked
            )
            show_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            show_item.setData(_ROLE_IDX, idx)
            self._table.setItem(row, 0, show_item)

            # Col 1 — Name
            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setForeground(QtGui.QColor(THEME["accent_checked_text"]))
            name_item.setData(_ROLE_IDX, idx)
            self._table.setItem(row, 1, name_item)

            # Col 2 — Time
            time_item = QtWidgets.QTableWidgetItem(
                f"{t_us * self._unit_scale:.3f}"
            )
            time_item.setData(_ROLE_IDX, idx)
            self._table.setItem(row, 2, time_item)

            # Col 3 — Depth
            depth_item = QtWidgets.QTableWidgetItem()
            depth_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, depth)
            depth_item.setData(_ROLE_IDX, idx)
            self._table.setItem(row, 3, depth_item)

            self._table.resizeColumnsToContents()
            pad_columns_for_sort_indicator(self._table)
            self._table.setColumnWidth(0, 50)
        finally:
            self._updating = False

    def _rebuild_table(self) -> None:
        """Rebuild all rows from self._bookmarks (used after deletion)."""
        self._updating = True
        try:
            self._table.setRowCount(0)
            saved = list(self._bookmarks)
            self._bookmarks.clear()
            for bm in saved:
                self._add_bookmark(bm["name"], bm["t_us"], bm["depth"], bm["visible"])
        finally:
            self._updating = False

    def _remove_bookmark(self, idx: int) -> None:
        if not (0 <= idx < len(self._bookmarks)):
            return
        self._bookmarks.pop(idx)
        self._rebuild_table()
        self._persist()

    def _persist(self) -> None:
        self.bookmarks_changed.emit(list(self._bookmarks))

    # ── Event handlers ────────────────────────────────────────────────

    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._updating or item.column() != 0:
            return
        idx = item.data(_ROLE_IDX)
        if idx is not None and 0 <= idx < len(self._bookmarks):
            self._bookmarks[idx]["visible"] = (
                item.checkState() == QtCore.Qt.CheckState.Checked
            )
            self._persist()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col == 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        idx = item.data(_ROLE_IDX)
        if idx is not None and 0 <= idx < len(self._bookmarks):
            self.activated.emit(self._bookmarks[idx]["t_us"])

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self._table.itemAt(pos)
        if item is None:
            return
        idx = item.data(_ROLE_IDX)
        if idx is None:
            return
        menu = QtWidgets.QMenu(self._table)
        rename_act = QtGui.QAction("Rename bookmark", menu)
        rename_act.triggered.connect(lambda: self._rename_bookmark(idx))
        menu.addAction(rename_act)
        remove_act = QtGui.QAction("Remove bookmark", menu)
        remove_act.triggered.connect(lambda: self._remove_bookmark(idx))
        menu.addAction(remove_act)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _rename_bookmark(self, idx: int) -> None:
        if not (0 <= idx < len(self._bookmarks)):
            return
        current = self._bookmarks[idx]["name"]
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename Bookmark", "Name:", text=current
        )
        if not ok or not new_name.strip():
            return
        self._bookmarks[idx]["name"] = new_name.strip()
        self._rebuild_table()
        self._persist()
