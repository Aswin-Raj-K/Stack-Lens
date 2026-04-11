"""Shared helpers for sortable dock tables.

Qt treats ``Qt::EditRole`` and ``Qt::DisplayRole`` as equivalent on
``QTableWidgetItem`` (and ``QTreeWidgetItem``) — setting one overwrites
the other — so the common "store float in EditRole, format in
DisplayRole" pattern doesn't actually give you numeric sorting. And
Qt's default ``operator<`` sorts by ``DisplayRole``, which for
formatted strings like ``"1000.000"`` and ``"20.000"`` means
lexicographic order (``"1000" < "20"``).

The fix used here: stash the raw numeric sort key in a dedicated
``UserRole`` (``SORT_KEY_ROLE``) that Qt won't touch, then override
``__lt__`` on a ``QTableWidgetItem`` subclass to compare by that
UserRole. Falling back to ``super().__lt__`` recurses infinitely in
PySide6 (the Python override is called from C++ polymorphically), so
we handle the fallback ourselves via ``text()``.
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .theme import THEME


# Dedicated role for the numeric sort key — independent of Display/Edit.
SORT_KEY_ROLE = QtCore.Qt.ItemDataRole.UserRole + 100


def pad_columns_for_sort_indicator(table, arrow_px=20, skip_cols=(0,)):
    """Add headroom to every sortable column so the sort-indicator arrow
    (and any bold font widening) never clips the header text.

    Call right after ``QTableWidget.resizeColumnsToContents()``. That
    method sizes each column to exactly fit the widest cell or header
    text — **without** accounting for stylesheet padding, the sort
    arrow's reserved region, or the fact that the header font is bold
    (metrics report unbold width). Here we add a fixed ``arrow_px`` to
    every non-skipped column on top of whatever the auto-size gave us,
    which is simple and always correct. The CSS ``padding-right: 22px``
    on ``QHeaderView::section`` reserves the chevron zone, so this
    extra width only guards against bold-font metric rounding.

    ``skip_cols`` lists columns whose width is fixed externally (e.g. a
    50-px checkbox column) and shouldn't be touched.
    """
    for col in range(table.columnCount()):
        if col in skip_cols:
            continue
        table.setColumnWidth(col, table.columnWidth(col) + arrow_px)


class SortableHeader(QtWidgets.QHeaderView):
    """Horizontal header view that draws a chevron (∧/∨) sort indicator.

    Strategy: suppress text in CE_Header so only the background/state is
    drawn by Qt, then draw the text *and* chevron ourselves both anchored to
    ``SE_HeaderLabel.center().y()``.  Because both items share the exact same
    reference rect there can be no vertical misalignment regardless of font
    metrics, CSS padding, or integer-rounding differences.

    Usage with QTableWidget::

        hdr = SortableHeader(table)
        table.setHorizontalHeader(hdr)
        hdr.setSortIndicator(col, Qt.SortOrder.DescendingOrder)

    Usage with QTreeWidget::

        hdr = SortableHeader(tree)
        tree.setHeader(hdr)
        hdr.setSortIndicator(col, Qt.SortOrder.DescendingOrder)

    Pass ``no_sort_cols`` to disable sorting (and hover highlight) on specific
    column indices::

        hdr = SortableHeader(table, no_sort_cols={0})
    """

    _CX_FROM_RIGHT = 14   # distance from section right edge to chevron centre-x
    _HALF_W = 4            # half-width  of the ∧/∨ chevron (px)
    _HALF_H = 3            # half-height of the ∧/∨ chevron (px)
    # Colors are read from THEME at paint time so theme switches take effect.

    def __init__(self, parent=None, no_sort_cols=()):
        super().__init__(QtCore.Qt.Orientation.Horizontal, parent)
        self._no_sort_cols = set(no_sort_cols)

    def mousePressEvent(self, event):  # noqa: N802
        col = self.logicalIndexAt(event.pos())
        if col in self._no_sort_cols:
            event.accept()
            return
        super().mousePressEvent(event)

    # ── helpers ──────────────────────────────────────────────────────

    def _build_opt(self, rect, logical_index):
        """Return a fully populated QStyleOptionHeader for *logical_index*."""
        opt = QtWidgets.QStyleOptionHeader()
        self.initStyleOption(opt)
        opt.rect    = rect
        opt.section = logical_index

        visual = self.visualIndex(logical_index)
        last   = self.count() - 1
        SP = QtWidgets.QStyleOptionHeader.SectionPosition
        if last == 0:
            opt.position = SP.OnlyOneSection
        elif visual == 0:
            opt.position = SP.Beginning
        elif visual == last:
            opt.position = SP.End
        else:
            opt.position = SP.Middle

        state = QtWidgets.QStyle.StateFlag.State_None
        if self.isEnabled():
            state |= QtWidgets.QStyle.StateFlag.State_Enabled
        if self.window().isActiveWindow():
            state |= QtWidgets.QStyle.StateFlag.State_Active
        if self.sectionsClickable() and logical_index not in self._no_sort_cols:
            lp = self.mapFromGlobal(QtGui.QCursor.pos())
            if rect.contains(lp):
                state |= QtWidgets.QStyle.StateFlag.State_MouseOver
                if QtWidgets.QApplication.mouseButtons() & QtCore.Qt.MouseButton.LeftButton:
                    state |= QtWidgets.QStyle.StateFlag.State_Sunken
                else:
                    state |= QtWidgets.QStyle.StateFlag.State_Raised
            else:
                state |= QtWidgets.QStyle.StateFlag.State_Raised
        opt.state = state

        model = self.model()
        if model is not None:
            data = model.headerData(
                logical_index, self.orientation(),
                QtCore.Qt.ItemDataRole.DisplayRole,
            )
            opt.text = str(data) if data is not None else ""
        else:
            opt.text = ""

        opt.sortIndicator = QtWidgets.QStyleOptionHeader.SortIndicator.None_
        return opt

    # ── painting ─────────────────────────────────────────────────────

    def paintSection(self, painter, rect, logical_index):
        if not rect.isValid():
            return

        # Capture the styled font Qt set on the painter before we touch it.
        # QHeaderView.paintEvent() calls painter.setFont(self.font()) which
        # includes CSS font-weight:bold, so this is the correct draw font.
        draw_font = painter.font()

        opt = self._build_opt(rect, logical_index)

        # ── 1. Draw background + state only (no text) ────────────────
        # We blank opt.text so CE_Header paints the background/hover/pressed
        # chrome without any text — we draw the text ourselves in step 2 so
        # that it shares the *exact same* cy as the chevron.
        painter.save()
        opt.text = ""
        self.style().drawControl(
            QtWidgets.QStyle.ControlElement.CE_Header, opt, painter, self
        )
        painter.restore()

        # ── 2. Find the label rect Qt uses for text ───────────────────
        # Restore the text for SE_HeaderLabel so the style can measure it.
        model = self.model()
        if model is not None:
            data = model.headerData(
                logical_index, self.orientation(),
                QtCore.Qt.ItemDataRole.DisplayRole,
            )
            opt.text = str(data) if data is not None else ""

        label_rect = self.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_HeaderLabel, opt, self
        )

        # ── 3. Draw text in label_rect ────────────────────────────────
        painter.save()
        painter.setClipRect(rect)
        painter.setFont(draw_font)
        is_hover = bool(opt.state & QtWidgets.QStyle.StateFlag.State_MouseOver)
        text_color = THEME["header_hover_text"] if is_hover else THEME["text_primary"]
        painter.setPen(QtGui.QColor(text_color))
        fm = QtGui.QFontMetrics(draw_font)
        elided = fm.elidedText(
            opt.text, QtCore.Qt.TextElideMode.ElideRight, label_rect.width()
        )
        # Shared vertical reference: section-rect centre (integer pixel).
        # We use the baseline drawText form so the optical centre of
        # uppercase glyphs lands exactly on cy.
        # AlignVCenter would centre the full bounding-box (ascent+descent),
        # pushing the visual mid-point slightly above cy because descenders
        # inflate the box downward.  capHeight() removes that bias.
        cy = rect.center().y()
        baseline_y = cy + (fm.capHeight() + 1) // 2
        painter.drawText(label_rect.left(), baseline_y, elided)
        painter.restore()

        # ── 4. Draw chevron at the same cy ───────────────────────────
        if logical_index != self.sortIndicatorSection():
            return

        cy  = rect.center().y()   # same value; explicit for clarity
        cx  = rect.right() - self._CX_FROM_RIGHT
        hw, hh = self._HALF_W, self._HALF_H
        ascending = (
            self.sortIndicatorOrder() == QtCore.Qt.SortOrder.AscendingOrder
        )
        if ascending:   # ∧
            pts = [QtCore.QPointF(cx - hw, cy + hh),
                   QtCore.QPointF(cx,       cy - hh),
                   QtCore.QPointF(cx + hw,  cy + hh)]
        else:           # ∨
            pts = [QtCore.QPointF(cx - hw, cy - hh),
                   QtCore.QPointF(cx,       cy + hh),
                   QtCore.QPointF(cx + hw,  cy - hh)]

        pen = QtGui.QPen(QtGui.QColor(THEME["text_secondary"]), 1.5)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setClipRect(rect)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QtGui.QPolygonF(pts))
        painter.restore()


class NumericSortItem(QtWidgets.QTableWidgetItem):
    """QTableWidgetItem that sorts by a UserRole-stored numeric key.

    Use ``setSortKey(value)`` to attach a float/int sort key. When Qt
    sorts the column, ``__lt__`` reads that key and compares numerically.
    Rows without a sort key fall back to a stable lexicographic compare
    on the display text.
    """

    def setSortKey(self, value):
        self.setData(SORT_KEY_ROLE, float(value))

    def __lt__(self, other):
        a = self.data(SORT_KEY_ROLE)
        b = other.data(SORT_KEY_ROLE) if isinstance(other, QtWidgets.QTableWidgetItem) else None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) < float(b)
        # Do NOT call super().__lt__ — it recurses into this Python
        # override from C++ and segfaults. Fall back to text compare.
        return self.text() < (other.text() if isinstance(other, QtWidgets.QTableWidgetItem) else "")
