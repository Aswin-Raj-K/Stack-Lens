"""Hierarchical call-tree dock with inclusive/exclusive timing."""

from PySide6 import QtCore, QtGui, QtWidgets

from span_builder import build_call_tree

from .dock_base import DockBase
from .sort_helpers import SortableHeader


# Custom roles for storing raw-microsecond values on tree items
_ROLE_INCLUSIVE_US = QtCore.Qt.ItemDataRole.UserRole + 1
_ROLE_EXCLUSIVE_US = QtCore.Qt.ItemDataRole.UserRole + 2
# Numeric-sort key for columns whose display text is a formatted string
# (e.g. "1.234" or "12.3%") but we want to sort by the raw float value.
_ROLE_NUMERIC_SORT = QtCore.Qt.ItemDataRole.UserRole + 3


class _SortableTreeItem(QtWidgets.QTreeWidgetItem):
    """QTreeWidgetItem that sorts numeric columns by stored float values
    instead of lexicographic text order.

    Column 0 (Function) still sorts by text. Columns 1-5 sort by the
    value stashed in the `_ROLE_NUMERIC_SORT` UserRole.
    """

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col == 0:
            return self.text(0).lower() < other.text(0).lower()
        a = self.data(col, _ROLE_NUMERIC_SORT)
        b = other.data(col, _ROLE_NUMERIC_SORT)
        if a is None or b is None:
            return self.text(col) < other.text(col)
        return float(a) < float(b)


class CallTreeDock(DockBase):
    """Tree view of aggregated function calls.

    Columns:
        Function | Calls | Inclusive | Exclusive | Self % | Total %

    Inclusive = span duration (including children)
    Exclusive = span duration minus direct children
    Self %    = exclusive / total-run-time
    Total %   = inclusive / total-run-time

    Signals:
        function_clicked(name) — user clicked a row
    """

    function_clicked = QtCore.Signal(str)

    def __init__(self, spans, color_map, total_us, parent=None):
        super().__init__("Call Tree", parent)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)

        self._color_map = color_map
        self._total_us = max(total_us, 1e-9)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setColumnCount(6)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        # Click-header-to-sort (sorts siblings within each parent)
        self._tree.setSortingEnabled(True)
        self._tree.setHeader(SortableHeader(self._tree))

        header = self._tree.header()
        for col in range(5):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        # Discoverability cues for sorting
        header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        # Default sort: Inclusive time descending (mirrors original build order)
        header.setSortIndicator(2, QtCore.Qt.SortOrder.DescendingOrder)

        self._tree.itemClicked.connect(
            lambda item, col: self.function_clicked.emit(item.text(0))
        )
        self.setWidget(self._tree)

        self._apply_headers()
        self.set_spans(spans, total_us)

    # ── Public API ──────────────────────────────────────────────────

    def set_spans(self, spans, total_us, color_map=None):
        """Rebuild the tree from a new span list."""
        if color_map is not None:
            self._color_map = color_map
        self._total_us = max(total_us, 1e-9)

        # Disable sorting during populate — otherwise each addChild
        # triggers a re-sort mid-populate.
        self._tree.setSortingEnabled(False)
        try:
            self._tree.clear()
            root = build_call_tree(spans)

            top_children = sorted(
                root["children"].values(),
                key=lambda n: n["inclusive_us"],
                reverse=True,
            )
            for child in top_children:
                self._tree.addTopLevelItem(self._make_item(child))

            # resizeColumnToContents ignores QSS padding, sort-indicator
            # space, and bold font metrics widening, so unconditionally
            # add 36 px of headroom per column (matches the helper used
            # for QTableWidget docks).
            for col in range(6):
                self._tree.resizeColumnToContents(col)
                self._tree.setColumnWidth(col, self._tree.columnWidth(col) + 36)
        finally:
            self._tree.setSortingEnabled(True)

        # Expand the first level by default
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setExpanded(True)

    def set_unit(self, unit_label, unit_scale):
        """Switch display unit between 'us' and 'ms'."""
        super().set_unit(unit_label, unit_scale)
        self._tree.setSortingEnabled(False)
        try:
            self._apply_headers()
            # Walk all items and update their time-column text
            for i in range(self._tree.topLevelItemCount()):
                self._update_item_text(self._tree.topLevelItem(i))
        finally:
            self._tree.setSortingEnabled(True)

    # ── Internal ────────────────────────────────────────────────────

    def _apply_headers(self):
        u = self._unit_label
        self._tree.setHeaderLabels([
            "Function", "Calls", f"Inclusive ({u})", f"Exclusive ({u})", "Self %", "Total %"
        ])
        tooltips = [
            "Click header to sort by function name",
            "Click header to sort by call count",
            f"Click header to sort by inclusive time ({u})",
            f"Click header to sort by exclusive time ({u})",
            "Click header to sort by Self %",
            "Click header to sort by Total %",
        ]
        header = self._tree.headerItem()
        for col, tip in enumerate(tooltips):
            header.setToolTip(col, tip)

    def _make_item(self, node):
        total_pct = 100.0 * node["inclusive_us"] / self._total_us
        self_pct = 100.0 * node["exclusive_us"] / self._total_us

        count = int(node["count"])
        inc_scaled = node["inclusive_us"] * self._unit_scale
        exc_scaled = node["exclusive_us"] * self._unit_scale

        item = _SortableTreeItem([
            node["name"],
            str(count),
            f"{inc_scaled:.3f}",
            f"{exc_scaled:.3f}",
            f"{self_pct:.1f}",
            f"{total_pct:.1f}",
        ])
        # Stash raw us values so set_unit can reformat later without rebuilding
        item.setData(2, _ROLE_INCLUSIVE_US, float(node["inclusive_us"]))
        item.setData(3, _ROLE_EXCLUSIVE_US, float(node["exclusive_us"]))
        # Numeric-sort keys for _SortableTreeItem
        item.setData(1, _ROLE_NUMERIC_SORT, float(count))
        item.setData(2, _ROLE_NUMERIC_SORT, float(node["inclusive_us"]))
        item.setData(3, _ROLE_NUMERIC_SORT, float(node["exclusive_us"]))
        item.setData(4, _ROLE_NUMERIC_SORT, float(self_pct))
        item.setData(5, _ROLE_NUMERIC_SORT, float(total_pct))

        color = self._color_map.get(node["name"])
        if color:
            item.setForeground(0, QtGui.QColor(color))

        # Left-align all columns
        for col in range(6):
            item.setTextAlignment(
                col,
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            )

        for child in sorted(node["children"].values(), key=lambda n: n["inclusive_us"], reverse=True):
            item.addChild(self._make_item(child))

        return item

    def _update_item_text(self, item):
        """Recursively re-render the time columns using the current unit scale."""
        inc = item.data(2, _ROLE_INCLUSIVE_US)
        exc = item.data(3, _ROLE_EXCLUSIVE_US)
        if inc is not None:
            item.setText(2, f"{inc * self._unit_scale:.3f}")
        if exc is not None:
            item.setText(3, f"{exc * self._unit_scale:.3f}")
        for i in range(item.childCount()):
            self._update_item_text(item.child(i))
