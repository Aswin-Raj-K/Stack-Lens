"""Dockable function-summary table with show/hide checkboxes."""

from PySide6 import QtCore, QtGui, QtWidgets

from span_builder import compute_stats

from .dock_base import DockBase
from .sort_helpers import NumericSortItem, SortableHeader, pad_columns_for_sort_indicator


# Roles used to store per-item data for sorting + lookups
_ROLE_NAME = QtCore.Qt.ItemDataRole.UserRole + 1       # function name (on col 1)
_ROLE_RAW_US = QtCore.Qt.ItemDataRole.UserRole + 2     # raw microsecond value (on time cells)
_ROLE_STAT_KEY = QtCore.Qt.ItemDataRole.UserRole + 3   # which stat ("total"/"avg"/"max") — for refresh


class SummaryDock(DockBase):
    """Function stats table with a visibility checkbox per row.

    Signals:
        function_clicked(name)         — user clicked a row (not the checkbox)
        visibility_changed(hidden_set) — user toggled visibility; emits the
                                         current set of HIDDEN function names
    """

    function_clicked = QtCore.Signal(str)
    visibility_changed = QtCore.Signal(set)
    analyze_jitter_requested = QtCore.Signal(str)
    ribbon_requested = QtCore.Signal(str)

    def __init__(self, spans, color_map, parent=None):
        super().__init__("Function Summary", parent)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)

        self._color_map = color_map
        self._hidden = set()
        # Map from function name -> stats dict (raw us). Used to look up
        # current values when refreshing unit formatting after the user has
        # sorted rows by a column header.
        self._stats_by_name = {}
        self._updating = False  # guard against itemChanged loops
        self._search_text = ""  # current search filter (lowercased)

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
        self.search_edit.setPlaceholderText("Search functions...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        ctrl_layout.addWidget(self.search_edit, 1)

        layout.addWidget(ctrl)

        # Ctrl+F focuses the search box (scoped to this dock)
        focus_search = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+F"), self)
        focus_search.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
        focus_search.activated.connect(self._focus_search)

        # Table
        self._table = QtWidgets.QTableWidget()
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        # Click-header-to-sort — disabled during set_spans() population
        self._table.setHorizontalHeader(SortableHeader(self._table, no_sort_cols={0}))
        self._table.setSortingEnabled(True)
        header = self._table.horizontalHeader()
        header.setSortIndicator(3, QtCore.Qt.SortOrder.DescendingOrder)
        # Discoverability cues — hand cursor + clickable sections
        header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        # Right-click context menu for jitter analysis
        self._table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table, 1)

        self.setWidget(container)
        self.set_spans(spans, color_map)

    # ── Public API ──────────────────────────────────────────────────

    def set_spans(self, spans, color_map=None):
        """Rebuild the table from a new span list (used by live refresh)."""
        if color_map is not None:
            self._color_map = color_map

        stats = compute_stats(spans)
        # Cache stats dict for later refresh / lookup by name
        self._stats_by_name = dict(stats)

        ordered = sorted(stats.items(), key=lambda kv: kv[1]["total_us"], reverse=True)

        self._updating = True
        # CRUCIAL: disable sorting during population, otherwise each setItem
        # triggers a re-sort mid-populate and we end up with corrupted rows.
        self._table.setSortingEnabled(False)
        try:
            table = self._table
            table.clear()
            table.setRowCount(len(ordered))
            table.setColumnCount(6)

            for row, (name, s) in enumerate(ordered):
                # Show/hide checkbox cell (column 0)
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
                show_item.setData(_ROLE_NAME, name)  # stable lookup after sort
                table.setItem(row, 0, show_item)

                color = QtGui.QColor(self._color_map.get(name, "#888"))
                name_item = QtWidgets.QTableWidgetItem(name)
                name_item.setForeground(color)
                name_item.setData(_ROLE_NAME, name)
                table.setItem(row, 1, name_item)

                # Calls — numeric via EditRole so sort is numeric
                count_item = QtWidgets.QTableWidgetItem()
                count_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, int(s["count"]))
                count_item.setData(_ROLE_NAME, name)
                table.setItem(row, 2, count_item)

                # Time columns — placeholder text, numeric EditRole for sort,
                # and stat-key UserRole so _refresh_unit_columns can re-format.
                # Uses NumericSortItem so column-header sort compares the
                # EditRole float instead of lexicographic text compare.
                for col, key in ((3, "total"), (4, "avg"), (5, "max")):
                    time_item = NumericSortItem()
                    time_item.setData(_ROLE_NAME, name)
                    time_item.setData(_ROLE_STAT_KEY, key)
                    table.setItem(row, col, time_item)

            self._refresh_unit_columns()

            table.resizeColumnsToContents()
            pad_columns_for_sort_indicator(table)
            table.setColumnWidth(0, 50)
        finally:
            self._updating = False
            self._table.setSortingEnabled(True)

        # Re-apply search filter so it survives refreshes
        self._apply_filter()

    def set_unit(self, unit_label, unit_scale):
        """Switch display unit between 'us' and 'ms' (purely a display change)."""
        super().set_unit(unit_label, unit_scale)
        self._updating = True
        self._table.setSortingEnabled(False)
        try:
            self._refresh_unit_columns()
        finally:
            self._updating = False
            self._table.setSortingEnabled(True)

    def _refresh_unit_columns(self):
        """Rewrite headers and time-column cell text for the current unit.

        Iterates rows in their current (possibly user-sorted) order and
        reads each row's function name from the name cell's UserRole data,
        then looks up the raw stats in `self._stats_by_name`.
        """
        u = self._unit_label
        s = self._unit_scale
        self._table.setHorizontalHeaderLabels(
            ["Show", "Function", "Calls", f"Total ({u})", f"Avg ({u})", f"Max ({u})"]
        )
        # Per-column tooltips so users discover click-to-sort
        tooltips = [
            "Click header to sort by visibility (shown/hidden)",
            "Click header to sort by function name",
            "Click header to sort by call count",
            f"Click header to sort by total time ({u})",
            f"Click header to sort by average time ({u})",
            f"Click header to sort by max time ({u})",
        ]
        for col, tip in enumerate(tooltips):
            item = self._table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(tip)
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 1)
            if name_item is None:
                continue
            name = name_item.data(_ROLE_NAME)
            stats = self._stats_by_name.get(name)
            if stats is None:
                continue
            total = stats["total_us"] * s
            avg = (stats["total_us"] / stats["count"]) * s if stats["count"] else 0.0
            mx = stats["max_us"] * s

            for col, raw in ((3, total), (4, avg), (5, mx)):
                item = self._table.item(row, col)
                if item is None:
                    continue
                # DisplayRole = formatted string; numeric sort key lives
                # in a dedicated UserRole on NumericSortItem.
                item.setData(QtCore.Qt.ItemDataRole.DisplayRole, f"{raw:.3f}")
                if isinstance(item, NumericSortItem):
                    item.setSortKey(float(raw))

    def scroll_to_function(self, name: str) -> None:
        """Clear search filter, select, and scroll to the row for *name*."""
        # Clear any active filter so the row isn't hidden
        if self._search_text:
            self.search_edit.clear()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 1)
            if item is not None and item.data(_ROLE_NAME) == name:
                self._table.selectRow(row)
                self._table.scrollToItem(item, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
                break

    def hidden_names(self):
        return set(self._hidden)

    def restore_hidden(self, names) -> None:
        """Restore a saved hidden-function set (called on session load).

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

    def _focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()
        # Raise the dock so it's visible if tabbed behind another
        self.raise_()

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
            return  # handled via itemChanged for checkbox
        name_item = self._table.item(row, 1)
        if name_item is None:
            return
        name = name_item.data(_ROLE_NAME)
        if name:
            self.function_clicked.emit(name)

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
        """Right-click on a row → context menu with 'Analyze Period / Jitter'."""
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
        ribbon_action = QtGui.QAction("Show in Ribbon View", menu)
        ribbon_action.triggered.connect(lambda: self.ribbon_requested.emit(name))
        menu.addAction(ribbon_action)
        menu.exec(self._table.viewport().mapToGlobal(pos))
