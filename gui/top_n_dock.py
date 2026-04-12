"""Top-N Slowest Calls dock.

Lists the N longest individual span instances in the trace (not averaged).
Click a row to jump to and flash-highlight that exact call on the flame chart.
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .dock_base import DockBase
from .sort_helpers import NumericSortItem, SortableHeader, pad_columns_for_sort_indicator
from .theme import spinbox_qss, THEME

DEFAULT_N = 50

# UserRole key — stores the index into self._top_spans on each cell so
# click handlers still map to the right span after header sort.
_ROLE_SPAN_IDX = QtCore.Qt.ItemDataRole.UserRole + 1
_ROLE_STAT_KEY = QtCore.Qt.ItemDataRole.UserRole + 2  # "duration" / "start"


class TopNSlowestDock(DockBase):
    """Right-side dock listing the slowest individual span instances.

    Signals:
        span_clicked(object)  — user clicked a row; payload is the span dict,
                                so the main window can jump to that exact call
                                (not just the first occurrence by name).
    """

    span_clicked = QtCore.Signal(object)

    def __init__(self, spans, color_map, parent=None):
        super().__init__("Top Slowest Calls", parent)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)

        self._color_map = color_map
        self._top_spans = []   # raw us values for the current top-N list
        self._n = DEFAULT_N
        self._updating = False

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Control panel strip — styled via QWidget#DockCtrlPanel in stylesheet
        ctrl_widget = QtWidgets.QWidget()
        ctrl_widget.setObjectName("DockCtrlPanel")
        ctrl_row = QtWidgets.QHBoxLayout(ctrl_widget)
        ctrl_row.setContentsMargins(6, 5, 6, 5)
        ctrl_row.setSpacing(6)
        ctrl_row.addWidget(QtWidgets.QLabel("Show top"))
        self._n_spin = QtWidgets.QSpinBox()
        self._n_spin.setRange(1, 1000)
        self._n_spin.setValue(self._n)
        self._n_spin.setKeyboardTracking(False)
        self._n_spin.valueChanged.connect(self._on_n_changed)
        self._n_spin.setStyleSheet(spinbox_qss("QSpinBox"))
        ctrl_row.addWidget(self._n_spin)
        ctrl_row.addWidget(QtWidgets.QLabel("calls"))
        ctrl_row.addStretch(1)
        layout.addWidget(ctrl_widget)

        # Table
        self._table = QtWidgets.QTableWidget()
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        # Click-header-to-sort — disabled during rebuild
        self._table.setHorizontalHeader(SortableHeader(self._table, no_sort_cols={0}))
        self._table.setSortingEnabled(True)
        header = self._table.horizontalHeader()
        header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table, 1)

        self.setWidget(container)
        self._all_spans = []
        self.set_spans(spans, color_map)

    # ── Public API ──────────────────────────────────────────────────

    def set_spans(self, spans, color_map=None):
        """Replace the underlying span list and rebuild the top-N view."""
        if color_map is not None:
            self._color_map = color_map
        self._all_spans = spans
        self._rebuild_table()

    def refresh_theme(self):
        """Reapply per-widget stylesheets after a theme change."""
        super().refresh_theme()
        self._n_spin.setStyleSheet(spinbox_qss("QSpinBox"))

    def set_unit(self, unit_label, unit_scale):
        """Switch display unit without re-sorting."""
        super().set_unit(unit_label, unit_scale)
        self._updating = True
        self._table.setSortingEnabled(False)
        try:
            self._refresh_unit_columns()
        finally:
            self._updating = False
            self._table.setSortingEnabled(True)

    # ── Internal ────────────────────────────────────────────────────

    def _on_n_changed(self, n):
        self._n = n
        self._rebuild_table()

    def _rebuild_table(self):
        self._top_spans = sorted(
            self._all_spans, key=lambda sp: sp["duration_us"], reverse=True
        )[: self._n]

        self._updating = True
        self._table.setSortingEnabled(False)
        try:
            table = self._table
            table.clear()
            table.setRowCount(len(self._top_spans))
            table.setColumnCount(5)

            for row, sp in enumerate(self._top_spans):
                # Rank — numeric EditRole for numeric sort
                rank_item = QtWidgets.QTableWidgetItem()
                rank_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, int(row + 1))
                rank_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                rank_item.setData(_ROLE_SPAN_IDX, row)
                table.setItem(row, 0, rank_item)

                # Function (colored)
                name_text = sp["name"]
                if sp.get("ipsr", 0) != 0:
                    name_text = f"{sp['name']}  [ISR {sp['ipsr']}]"
                name_item = QtWidgets.QTableWidgetItem(name_text)
                color = QtGui.QColor(self._color_map.get(sp["name"], "#888"))
                name_item.setForeground(color)
                name_item.setData(_ROLE_SPAN_IDX, row)
                table.setItem(row, 1, name_item)

                # Placeholder cells (filled by _refresh_unit_columns).
                # NumericSortItem so header-click compares EditRole floats.
                for col, key in ((2, "duration"), (3, "start")):
                    item = NumericSortItem()
                    item.setData(_ROLE_SPAN_IDX, row)
                    item.setData(_ROLE_STAT_KEY, key)
                    table.setItem(row, col, item)

                # Depth — numeric
                depth_item = QtWidgets.QTableWidgetItem()
                depth_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, int(sp["depth"]))
                depth_item.setData(_ROLE_SPAN_IDX, row)
                table.setItem(row, 4, depth_item)

            self._refresh_unit_columns()
            table.resizeColumnsToContents()
            pad_columns_for_sort_indicator(table)
            table.setColumnWidth(0, 40)
        finally:
            self._updating = False
            self._table.setSortingEnabled(True)

    def _refresh_unit_columns(self):
        u = self._unit_label
        s = self._unit_scale
        self._table.setHorizontalHeaderLabels(
            ["#", "Function", f"Duration ({u})", f"Start ({u})", "Depth"]
        )
        # Per-column tooltips — discoverability for click-to-sort
        tooltips = [
            "Click header to sort by rank",
            "Click header to sort by function name",
            f"Click header to sort by duration ({u})",
            f"Click header to sort by start time ({u})",
            "Click header to sort by call depth",
        ]
        for col, tip in enumerate(tooltips):
            item = self._table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(tip)

        # Compute relative start from the earliest span time across the whole
        # data set so positions line up with the main chart's X axis.
        if self._all_spans:
            t_min = min(sp["start_us"] for sp in self._all_spans)
        else:
            t_min = 0.0
        # Iterate rows — after sort, row order may differ from self._top_spans
        # order, so we pull the span index from UserRole.
        for row in range(self._table.rowCount()):
            idx_item = self._table.item(row, 0)
            if idx_item is None:
                continue
            idx = idx_item.data(_ROLE_SPAN_IDX)
            if idx is None or not (0 <= idx < len(self._top_spans)):
                continue
            sp = self._top_spans[idx]
            dur = sp["duration_us"] * s
            start = (sp["start_us"] - t_min) * s
            for col, raw in ((2, dur), (3, start)):
                item = self._table.item(row, col)
                if item is None:
                    continue
                item.setData(QtCore.Qt.ItemDataRole.DisplayRole, f"{raw:.3f}")
                if isinstance(item, NumericSortItem):
                    item.setSortKey(float(raw))

    def _on_cell_clicked(self, row, col):
        if self._updating:
            return
        # Pull the span index from UserRole on column 0 so post-sort row
        # still maps to the right span.
        idx_item = self._table.item(row, 0)
        if idx_item is None:
            return
        idx = idx_item.data(_ROLE_SPAN_IDX)
        if idx is None or not (0 <= idx < len(self._top_spans)):
            return
        self.span_clicked.emit(self._top_spans[idx])
