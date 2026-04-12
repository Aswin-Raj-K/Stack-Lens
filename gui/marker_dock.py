"""Dockable marker list — shows all TRACE_MARK events aggregated by name."""

from collections import defaultdict

from PySide6 import QtCore, QtGui, QtWidgets

from .dock_base import DockBase
from .sort_helpers import NumericSortItem, SortableHeader, pad_columns_for_sort_indicator
from .theme import THEME


# UserRole for storing the marker name on every cell in a row — survives
# column-header sorting so handlers can pull it from the item directly.
_ROLE_NAME = QtCore.Qt.ItemDataRole.UserRole + 1
_ROLE_STAT_KEY = QtCore.Qt.ItemDataRole.UserRole + 2  # "first"/"last"


class MarkerDock(DockBase):
    """Lists unique markers with count, first/last time, context, visibility.

    Signals:
        mark_clicked(name)              — user clicked a row (not the checkbox)
        visibility_changed(hidden_set)  — set of HIDDEN marker names
    """

    mark_clicked = QtCore.Signal(str)
    visibility_changed = QtCore.Signal(set)
    analyze_jitter_requested = QtCore.Signal(str)

    def __init__(self, marks, parent=None):
        super().__init__("Markers", parent)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)

        self._hidden = set()
        # Map name -> raw stats dict (unscaled microseconds). Used by
        # _refresh_unit_columns to look up values after header sort.
        self._stats_by_name = {}
        self._updating = False
        self._search_text = ""

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Control panel strip — styled via QWidget#DockCtrlPanel in stylesheet
        ctrl = QtWidgets.QWidget()
        ctrl.setObjectName("DockCtrlPanel")
        ctrl_layout = QtWidgets.QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(6, 5, 6, 5)
        ctrl_layout.setSpacing(6)
        show_btn = QtWidgets.QPushButton("Show All")
        hide_btn = QtWidgets.QPushButton("Hide All")
        show_btn.clicked.connect(self._show_all)
        hide_btn.clicked.connect(self._hide_all)
        ctrl_layout.addWidget(show_btn)
        ctrl_layout.addWidget(hide_btn)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search markers...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        ctrl_layout.addWidget(self.search_edit, 1)

        layout.addWidget(ctrl)

        self._table = QtWidgets.QTableWidget()
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        # Click-header-to-sort — disabled during set_marks() population
        self._table.setHorizontalHeader(SortableHeader(self._table))
        self._table.setSortingEnabled(True)
        header = self._table.horizontalHeader()
        header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table, 1)

        self.setWidget(container)
        self.set_marks(marks)

    # ── Public API ──────────────────────────────────────────────────

    def set_marks(self, marks):
        """Rebuild the table from a new marks list."""
        # Aggregate by name
        stats = defaultdict(lambda: {
            "count": 0,
            "first_us": float("inf"),
            "last_us": 0.0,
            "thread_calls": 0,
            "isr_calls": 0,
            "ipsr_seen": set(),
        })
        for m in marks or []:
            name = m["name"]
            t = m["t_us"]
            ipsr = m.get("ipsr", 0)
            s = stats[name]
            s["count"] += 1
            if t < s["first_us"]:
                s["first_us"] = t
            if t > s["last_us"]:
                s["last_us"] = t
            if ipsr == 0:
                s["thread_calls"] += 1
            else:
                s["isr_calls"] += 1
                s["ipsr_seen"].add(ipsr)

        self._stats_by_name = dict(stats)
        ordered = sorted(stats.items(), key=lambda kv: kv[1]["first_us"])

        self._updating = True
        # CRUCIAL: disable sorting during population (Qt would re-sort
        # on every setItem call and corrupt row state).
        self._table.setSortingEnabled(False)
        try:
            table = self._table
            table.clear()
            table.setRowCount(len(ordered))
            table.setColumnCount(6)

            for row, (name, s) in enumerate(ordered):
                # Checkbox (column 0)
                show_item = QtWidgets.QTableWidgetItem()
                show_item.setFlags(
                    QtCore.Qt.ItemFlag.ItemIsUserCheckable
                    | QtCore.Qt.ItemFlag.ItemIsEnabled
                )
                show_item.setCheckState(
                    QtCore.Qt.CheckState.Unchecked
                    if name in self._hidden
                    else QtCore.Qt.CheckState.Checked
                )
                show_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                show_item.setData(_ROLE_NAME, name)
                table.setItem(row, 0, show_item)

                # Name column — use mark color
                name_item = QtWidgets.QTableWidgetItem(name)
                name_item.setForeground(QtGui.QColor(THEME["status_mark"]))
                name_item.setData(_ROLE_NAME, name)
                table.setItem(row, 1, name_item)

                # Count — numeric via EditRole for numeric sort
                count_item = QtWidgets.QTableWidgetItem()
                count_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, int(s["count"]))
                count_item.setData(_ROLE_NAME, name)
                table.setItem(row, 2, count_item)

                # Placeholders for time columns — _refresh_unit_columns
                # fills DisplayRole + EditRole. NumericSortItem so the
                # EditRole float is used for sort comparison.
                for col, key in ((3, "first"), (4, "last")):
                    item = NumericSortItem()
                    item.setData(_ROLE_NAME, name)
                    item.setData(_ROLE_STAT_KEY, key)
                    table.setItem(row, col, item)

                # Context
                if s["isr_calls"] == 0:
                    ctx = "thread"
                elif s["thread_calls"] == 0:
                    ipsrs = sorted(s["ipsr_seen"])
                    ctx = "ISR " + ",".join(str(i) for i in ipsrs)
                else:
                    ctx = f"mixed ({s['thread_calls']} thread, {s['isr_calls']} ISR)"
                ctx_item = QtWidgets.QTableWidgetItem(ctx)
                ctx_item.setData(_ROLE_NAME, name)
                table.setItem(row, 5, ctx_item)

            self._refresh_unit_columns()
            table.resizeColumnsToContents()
            pad_columns_for_sort_indicator(table)
            table.setColumnWidth(0, 50)
        finally:
            self._updating = False
            self._table.setSortingEnabled(True)

        self._apply_filter()

    def set_unit(self, unit_label, unit_scale):
        """Switch time display unit between 'us' and 'ms'."""
        super().set_unit(unit_label, unit_scale)
        self._updating = True
        self._table.setSortingEnabled(False)
        try:
            self._refresh_unit_columns()
        finally:
            self._updating = False
            self._table.setSortingEnabled(True)

    def hidden_names(self):
        return set(self._hidden)

    def restore_hidden(self, names) -> None:
        """Restore a saved hidden-marker set (called on session load).

        Updates checkboxes in the current table and emits visibility_changed
        so the flame chart reacts immediately.
        """
        self._updating = True
        try:
            self._hidden = set(names)
            for row in range(self._table.rowCount()):
                it = self._table.item(row, 0)
                if it is None:
                    continue
                name = it.data(_ROLE_NAME)
                it.setCheckState(
                    QtCore.Qt.CheckState.Unchecked
                    if name in self._hidden
                    else QtCore.Qt.CheckState.Checked
                )
        finally:
            self._updating = False
        self.visibility_changed.emit(set(self._hidden))

    def _refresh_unit_columns(self):
        u = self._unit_label
        s = self._unit_scale
        self._table.setHorizontalHeaderLabels([
            "Show", "Marker", "Count", f"First ({u})", f"Last ({u})", "Context"
        ])
        # Per-column tooltips — discoverability for click-to-sort
        tooltips = [
            "Click header to sort by visibility (shown/hidden)",
            "Click header to sort by marker name",
            "Click header to sort by count",
            f"Click header to sort by first occurrence ({u})",
            f"Click header to sort by last occurrence ({u})",
            "Click header to sort by context",
        ]
        for col, tip in enumerate(tooltips):
            item = self._table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(tip)

        # Read each row's name from UserRole so sort doesn't break us
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if name_item is None:
                continue
            name = name_item.data(_ROLE_NAME)
            st = self._stats_by_name.get(name)
            if st is None:
                continue
            first = st["first_us"] * s
            last = st["last_us"] * s
            for col, raw in ((3, first), (4, last)):
                item = self._table.item(row, col)
                if item is None:
                    continue
                item.setData(QtCore.Qt.ItemDataRole.DisplayRole, f"{raw:.3f}")
                if isinstance(item, NumericSortItem):
                    item.setSortKey(float(raw))

    # ── Search filter ───────────────────────────────────────────────

    def _on_search_changed(self, text):
        self._search_text = text.lower()
        self._apply_filter()

    def _apply_filter(self):
        q = self._search_text
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if name_item is None:
                self._table.setRowHidden(row, False)
                continue
            name = (name_item.data(_ROLE_NAME) or "").lower()
            hidden = bool(q) and q not in name
            self._table.setRowHidden(row, hidden)

    # ── Signals ─────────────────────────────────────────────────────

    def _on_item_changed(self, item):
        if self._updating:
            return
        if item.column() != 0:
            return
        name = item.data(_ROLE_NAME)
        if not name:
            return
        if item.checkState() == QtCore.Qt.CheckState.Checked:
            self._hidden.discard(name)
        else:
            self._hidden.add(name)
        self.visibility_changed.emit(set(self._hidden))

    def _on_cell_clicked(self, row, col):
        if col == 0:
            return
        name_item = self._table.item(row, 1)
        if name_item is None:
            return
        name = name_item.data(_ROLE_NAME)
        if name:
            self.mark_clicked.emit(name)

    def _show_all(self):
        self._updating = True
        try:
            self._hidden.clear()
            for row in range(self._table.rowCount()):
                it = self._table.item(row, 0)
                if it:
                    it.setCheckState(QtCore.Qt.CheckState.Checked)
        finally:
            self._updating = False
        self.visibility_changed.emit(set(self._hidden))

    def _hide_all(self):
        self._updating = True
        try:
            all_names = set()
            for row in range(self._table.rowCount()):
                name_item = self._table.item(row, 1)
                if name_item is None:
                    continue
                name = name_item.data(_ROLE_NAME)
                if name:
                    all_names.add(name)
                it = self._table.item(row, 0)
                if it:
                    it.setCheckState(QtCore.Qt.CheckState.Unchecked)
            self._hidden = all_names
        finally:
            self._updating = False
        self.visibility_changed.emit(set(self._hidden))

    def _on_context_menu(self, pos):
        """Right-click on a row → 'Analyze Period / Jitter'."""
        item = self._table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        name_item = self._table.item(row, 1)
        if name_item is None:
            return
        name = name_item.data(_ROLE_NAME)
        if not name:
            return

        menu = QtWidgets.QMenu(self._table)
        analyze_action = QtGui.QAction("Analyze Period / Jitter", menu)
        analyze_action.triggered.connect(lambda: self.analyze_jitter_requested.emit(name))
        menu.addAction(analyze_action)
        menu.exec(self._table.viewport().mapToGlobal(pos))
