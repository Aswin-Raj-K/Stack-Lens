"""Flame-chart graphics item: fast, culled, solid-block renderer."""

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .constants import ROW_HEIGHT, VIRIDIS
from .theme import THEME, CANVAS_PAUSE_RGBA


class FlameItem(pg.GraphicsObject):
    """Flame chart with viewport culling, solid blocks, two color modes,
    ISR lane rendering, and timeline marks.

    Display coordinate system (Y, with pyqtgraph invertY=True so smaller y
    appears higher on screen):
        - Thread spans:  display_y = depth                  (0, 1, 2, ...)
        - ISR spans:     display_y = -(depth + 1)           (-1, -2, -3, ...)
                         so they appear ABOVE the thread lanes.
    """

    def __init__(self, spans, color_map, t_min, color_mode="function", marks=None, pause_regions=None,
                 row_height=None, font_size=None):
        super().__init__()
        self._t_min = t_min
        self._color_mode = color_mode
        self._hidden = set()
        self._hidden_marks = set()  # set of marker names to skip drawing
        self._highlighted_name = None
        self._pause_regions = []  # list of {x0, x1} (relative)
        self._show_bar_labels = False   # toggled via View menu — off by default
        self._show_mark_labels = False  # toggled via View > Show Marker Names
        self._show_sticky_hover = False  # sticky top-left hover label
        self._sticky_text = ""
        self._row_height = row_height if row_height is not None else ROW_HEIGHT
        self._chart_font_size = font_size if font_size is not None else 8

        # Viridis normalization from durations
        durations = [sp["duration_us"] for sp in spans if sp["duration_us"] > 0]
        if durations:
            d_min = min(durations)
            d_max = max(durations)
            log_min = math.log10(d_min) if d_min > 0 else 0.0
            log_max = math.log10(d_max) if d_max > 0 else 1.0
            log_range = max(log_max - log_min, 1e-9)
        else:
            log_min = 0.0
            log_range = 1.0

        self.duration_min_us = min(durations) if durations else 0.0
        self.duration_max_us = max(durations) if durations else 0.0

        n_viridis = len(VIRIDIS)

        def _dim(qc):
            d = QtGui.QColor(qc)
            d.setAlpha(40)
            return d

        # Bucket by display_y (thread: depth; ISR: -(depth+1)).
        self._by_depth = defaultdict(list)
        self._has_isr = False
        for sp in spans:
            x0 = sp["start_us"] - t_min
            x1 = sp["end_us"] - t_min
            ipsr = sp.get("ipsr", 0)
            if ipsr == 0:
                display_y = sp["depth"]
            else:
                display_y = -(sp["depth"] + 1)
                self._has_isr = True

            fn_color = QtGui.QColor(color_map.get(sp["name"], THEME["canvas_fallback"]))

            dur = sp["duration_us"]
            if dur > 0:
                log_d = math.log10(dur)
                t = (log_d - log_min) / log_range
                idx = max(0, min(n_viridis - 1, int(t * (n_viridis - 1))))
                dur_color = QtGui.QColor(VIRIDIS[idx])
            else:
                dur_color = QtGui.QColor(VIRIDIS[0])

            self._by_depth[display_y].append({
                "x0": x0,
                "x1": x1,
                "name": sp["name"],
                "fn_color": fn_color,
                "fn_color_dim": _dim(fn_color),
                "dur_color": dur_color,
                "dur_color_dim": _dim(dur_color),
            })

        for d in self._by_depth:
            self._by_depth[d].sort(key=lambda s: s["x0"])

        self._x0s = {d: [s["x0"] for s in lst] for d, lst in self._by_depth.items()}

        # Marks: precompute x positions relative to t_min for fast culling
        self._marks = []
        self.set_marks(marks or [])
        self.set_pause_regions(pause_regions or [])

        # User bookmarks — visible subset, in relative coords
        self._bookmarks_vis: list[dict] = []

        # Bounds: full data extent
        x_max = max(
            (s["x1"] for lst in self._by_depth.values() for s in lst),
            default=1.0,
        )
        if self._marks:
            x_max = max(x_max, max(m["x"] for m in self._marks))

        if self._by_depth:
            min_y = min(self._by_depth.keys())
            max_y = max(self._by_depth.keys()) + 1
        else:
            min_y = 0
            max_y = 1

        # Extend bounding rect a bit beyond the exact data Y range so that
        # full-height overlays (pause bands, marker lines) can paint into the
        # padding area the main plot view uses.
        self._bounds = QtCore.QRectF(
            0,
            min_y - 0.5,
            x_max,
            (max_y + 0.5) - (min_y - 0.5),
        )

        self.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption,
            True,
        )

    # ── Public API ──────────────────────────────────────────────────

    def set_hidden(self, names):
        self._hidden = set(names)
        self.update()

    def set_color_mode(self, mode):
        if mode not in ("function", "duration"):
            return
        self._color_mode = mode
        self.update()

    def set_highlighted_name(self, name):
        if name != self._highlighted_name:
            self._highlighted_name = name
            self.update()

    def set_marks(self, marks):
        """Replace the mark list and trigger a redraw."""
        self._marks = sorted(
            [{"x": m["t_us"] - self._t_min, "name": m["name"], "ipsr": m.get("ipsr", 0)} for m in marks],
            key=lambda m: m["x"],
        )
        self._mark_x = [m["x"] for m in self._marks]
        self.update()

    def set_bookmarks(self, bookmarks: list) -> None:
        """Replace the visible bookmark list and trigger a redraw.

        bm["t_us"] is already in item/plot coordinates (absolute_us - t_min),
        the same space as span x0/x1.  Do NOT subtract _t_min again.
        """
        self._bookmarks_vis = [
            {
                "x":     bm["t_us"],
                "depth": bm.get("depth", 0),
                "name":  bm["name"],
            }
            for bm in bookmarks
            if bm.get("visible", True)
        ]
        self.update()

    def set_row_height(self, value: float) -> None:
        """Change the row height (bar height in data units). Triggers a redraw."""
        value = float(value)
        if value != self._row_height:
            self._row_height = value
            self.update()

    def set_chart_font_size(self, size: int) -> None:
        """Change the font size for bar labels and bookmark labels."""
        size = int(size)
        if size != self._chart_font_size:
            self._chart_font_size = size
            self.update()

    def set_hidden_marks(self, names):
        """Set of marker names to hide from the chart."""
        self._hidden_marks = set(names)
        self.update()

    def set_pause_regions(self, regions):
        """Replace the pause-region list. Coords stored relative to t_min."""
        self._pause_regions = [
            {"x0": r["start_us"] - self._t_min, "x1": r["end_us"] - self._t_min}
            for r in (regions or [])
        ]
        self.update()

    def set_show_bar_labels(self, enabled):
        """Toggle rendering of elided function names inside bars."""
        enabled = bool(enabled)
        if self._show_bar_labels != enabled:
            self._show_bar_labels = enabled
            self.update()

    def set_show_mark_labels(self, enabled):
        """Toggle rendering of marker names on the flame chart."""
        enabled = bool(enabled)
        if self._show_mark_labels != enabled:
            self._show_mark_labels = enabled
            self.update()

    def set_show_sticky_hover(self, enabled):
        """Toggle rendering of the sticky top-left hover label."""
        enabled = bool(enabled)
        if self._show_sticky_hover != enabled:
            self._show_sticky_hover = enabled
            self.update()

    def set_sticky_text(self, text):
        """Update the sticky hover label text (no-op if label disabled)."""
        if text != self._sticky_text:
            self._sticky_text = text
            if self._show_sticky_hover:
                self.update()

    def color_for_span_name(self, name):
        for lst in self._by_depth.values():
            for s in lst:
                if s["name"] == name:
                    return s["fn_color"]
        return QtGui.QColor(THEME["canvas_fallback"])

    def nearest_mark(self, x_rel, tolerance_data):
        """Find the mark closest to ``x_rel`` within ``tolerance_data`` data units.

        Skips marks whose name is currently hidden. Returns the mark dict or None.
        """
        if not self._marks:
            return None
        i = bisect_left(self._mark_x, x_rel)
        candidates = []
        if i > 0:
            candidates.append(self._marks[i - 1])
        if i < len(self._marks):
            candidates.append(self._marks[i])
        best = None
        best_d = tolerance_data
        for m in candidates:
            if m["name"] in self._hidden_marks:
                continue
            d = abs(m["x"] - x_rel)
            if d <= best_d:
                best = m
                best_d = d
        return best

    def min_display_y(self):
        """Smallest display_y value — used by main_window to set Y range."""
        return min(self._by_depth.keys(), default=0)

    def max_display_y(self):
        """Largest display_y value."""
        return max(self._by_depth.keys(), default=0)

    def has_isr(self):
        return self._has_isr

    # ── QGraphicsItem ───────────────────────────────────────────────

    def boundingRect(self):
        return self._bounds

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)

        vis = option.exposedRect
        x_lo, x_hi = vis.left(), vis.right()
        y_lo, y_hi = vis.top(), vis.bottom()

        t = painter.transform()
        px_per_unit_x = abs(t.m11()) or 1.0
        min_data_w = 1.0 / px_per_unit_x

        depth_lo = int(math.floor(y_lo))
        depth_hi = int(math.ceil(y_hi)) + 1

        color_key = "fn_color" if self._color_mode == "function" else "dur_color"
        dim_key = color_key + "_dim"
        hidden = self._hidden
        hl = self._highlighted_name

        # ── Pause regions: gray bands UNDER the bars ──
        # The underlay is translucent so the spans on top stay readable; the
        # vertical edge lines guarantee even narrow bands stay visible.
        if self._pause_regions:
            pause_fill = QtGui.QColor(*CANVAS_PAUSE_RGBA)
            edge_pen = QtGui.QPen(QtGui.QColor(THEME["canvas_edge"]))
            edge_pen.setWidth(2)
            edge_pen.setCosmetic(True)
            top_y_full = self._bounds.top()
            bot_y_full = self._bounds.bottom()
            for r in self._pause_regions:
                if r["x1"] < x_lo or r["x0"] > x_hi:
                    continue
                w = r["x1"] - r["x0"]
                rect = QtCore.QRectF(r["x0"], top_y_full, w, bot_y_full - top_y_full)
                painter.fillRect(rect, pause_fill)
                # Vertical edge lines so narrow bands stay visible
                painter.setPen(edge_pen)
                painter.drawLine(
                    QtCore.QPointF(r["x0"], top_y_full),
                    QtCore.QPointF(r["x0"], bot_y_full),
                )
                painter.drawLine(
                    QtCore.QPointF(r["x1"], top_y_full),
                    QtCore.QPointF(r["x1"], bot_y_full),
                )

        for depth in range(depth_lo, depth_hi + 1):
            lst = self._by_depth.get(depth)
            if not lst:
                continue
            x0s = self._x0s[depth]

            i_start = max(0, bisect_left(x0s, x_lo) - 1)
            i_end = bisect_right(x0s, x_hi)

            for i in range(i_start, i_end):
                s = lst[i]
                if s["name"] in hidden:
                    continue
                if s["x1"] < x_lo:
                    continue
                if s["x0"] > x_hi:
                    break

                w = s["x1"] - s["x0"]
                draw_w = max(w, min_data_w)
                rect = QtCore.QRectF(s["x0"], depth, draw_w, self._row_height)

                if hl is not None and s["name"] != hl:
                    painter.fillRect(rect, s[dim_key])
                else:
                    painter.fillRect(rect, s[color_key])

        # ── Pause regions: dim overlay + 'PAUSED' label on top of bars ──
        if self._pause_regions:
            top_y_full = self._bounds.top()
            bot_y_full = self._bounds.bottom()
            overlay = QtGui.QColor(30, 30, 35, 110)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            for r in self._pause_regions:
                if r["x1"] < x_lo or r["x0"] > x_hi:
                    continue
                rect = QtCore.QRectF(r["x0"], top_y_full, r["x1"] - r["x0"], bot_y_full - top_y_full)
                painter.fillRect(rect, overlay)

            # 'PAUSED' label centered on each visible band (screen pixels)
            # Anchor at the MAX of bounds-top and the exposed viewport top,
            # otherwise the bounds-top may be above the visible area and the
            # text gets clipped to just the bottoms of the letters.
            label_anchor_y = max(top_y_full, y_lo)
            painter.save()
            painter.resetTransform()
            painter.setPen(QtGui.QColor(THEME["text_primary"]))
            font = QtGui.QFont("Segoe UI", 10, QtGui.QFont.Weight.Bold)
            painter.setFont(font)
            for r in self._pause_regions:
                if r["x1"] < x_lo or r["x0"] > x_hi:
                    continue
                center_data = (r["x0"] + r["x1"]) / 2
                # Skip label if band is too narrow (< 40 px)
                if (r["x1"] - r["x0"]) * px_per_unit_x < 40:
                    continue
                pt = t.map(QtCore.QPointF(center_data, label_anchor_y))
                painter.drawText(
                    QtCore.QRectF(pt.x() - 60, pt.y() + 4, 120, 20),
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    "PAUSED",
                )
            painter.restore()

        # ── Marks: bright vertical lines spanning full Y with a flag label ──
        if self._marks:
            top_y = self._bounds.top()
            bot_y = self._bounds.bottom()

            # Cull: only marks inside the exposed x range (with a small margin
            # so labels drawn above aren't clipped at viewport edge)
            margin = 20.0 / px_per_unit_x
            i_lo = max(0, bisect_left(self._mark_x, x_lo - margin) - 1)
            i_hi = bisect_right(self._mark_x, x_hi + margin)

            line_pen = QtGui.QPen(QtGui.QColor(THEME["selection"]))
            line_pen.setWidth(2)
            line_pen.setCosmetic(True)  # 2 pixels regardless of zoom
            painter.setPen(line_pen)

            mark_color = QtGui.QColor(THEME["selection"])
            flag_height = 0.35  # data units, placed just below top_y

            show_labels = self._show_mark_labels
            lbl_font = QtGui.QFont("Segoe UI", self._chart_font_size) if show_labels else None
            # Bottom anchor: clamp to visible bottom so labels stay on-screen.
            lbl_anchor_y = min(bot_y, y_hi)

            hidden_marks = self._hidden_marks

            # Pass 1 — lines + triangles (always drawn).
            # Collect (x_px, y_base_px, label_text, label_width) for pass 2.
            label_entries = [] if show_labels else None
            fm = QtGui.QFontMetrics(lbl_font) if show_labels else None

            for i in range(i_lo, i_hi):
                m = self._marks[i]
                if m["name"] in hidden_marks:
                    continue
                x = m["x"]
                if x < x_lo - margin or x > x_hi + margin:
                    continue

                # Vertical line
                painter.drawLine(QtCore.QPointF(x, top_y), QtCore.QPointF(x, bot_y))

                # Filled triangle flag at the top
                tri = QtGui.QPolygonF([
                    QtCore.QPointF(x, top_y),
                    QtCore.QPointF(x - 0.3 / px_per_unit_x * 6, top_y - flag_height),
                    QtCore.QPointF(x + 0.3 / px_per_unit_x * 6, top_y - flag_height),
                ])
                painter.setBrush(QtGui.QBrush(mark_color))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon(tri)
                painter.setPen(line_pen)

                if show_labels:
                    pt_px = t.map(QtCore.QPointF(x, lbl_anchor_y))
                    label = "\U0001f6a9 " + m["name"]
                    label_entries.append((pt_px.x(), pt_px.y(), label,
                                          fm.horizontalAdvance(label)))

            # Pass 2 — staggered labels.
            # Each label is assigned to the first stagger level where it doesn't
            # overlap the previous label at that level.  Labels fan upward so
            # closely-spaced markers remain readable.
            if show_labels and label_entries:
                LINE_H   = fm.height() + 2   # vertical step per stagger level
                MAX_LVL  = 5                 # cap stagger depth
                PAD_PX   = 6                 # horizontal gap between labels
                # rightmost pixel edge used so far at each level
                lvl_right = [-9999.0] * MAX_LVL

                painter.save()
                painter.resetTransform()
                painter.setFont(lbl_font)
                painter.setPen(mark_color)

                for x_px, y_base, label, w in label_entries:
                    lx = x_px + 4
                    # find lowest free level
                    lvl = next((l for l in range(MAX_LVL) if lx >= lvl_right[l]),
                               MAX_LVL - 1)
                    lvl_right[lvl] = lx + w + PAD_PX
                    painter.drawText(
                        QtCore.QPointF(lx, y_base - 4 - lvl * LINE_H),
                        label,
                    )

                painter.restore()
                painter.setPen(line_pen)

        # ── Bookmark markers ───────────────────────────────────────
        if self._bookmarks_vis:
            _top_y  = self._bounds.top()
            _bot_y  = self._bounds.bottom()
            _margin = 20.0 / px_per_unit_x
            bm_color = QtGui.QColor(THEME["accent_checked_text"])
            bm_pen   = QtGui.QPen(bm_color)
            bm_pen.setWidth(1)
            bm_pen.setCosmetic(True)
            bm_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            lbl_font = QtGui.QFont("Segoe UI", self._chart_font_size)

            for bm in self._bookmarks_vis:
                x = bm["x"]
                if x < x_lo - _margin or x > x_hi + _margin:
                    continue

                # Full-height dashed vertical line
                painter.setPen(bm_pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawLine(QtCore.QPointF(x, _top_y), QtCore.QPointF(x, _bot_y))

                # Thick solid segment at the bookmarked depth row
                thick_pen = QtGui.QPen(bm_color)
                thick_pen.setWidth(3)
                thick_pen.setCosmetic(True)
                row_top = float(bm["depth"])
                row_bot = row_top + self._row_height
                # I-beam: cap half-width = 5 px converted to data units
                cap_hw = 5.0 / (abs(t.m11()) or 1.0)
                painter.setPen(thick_pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                # Vertical stem
                painter.drawLine(QtCore.QPointF(x, row_top), QtCore.QPointF(x, row_bot))
                # Top cap
                painter.drawLine(QtCore.QPointF(x - cap_hw, row_top), QtCore.QPointF(x + cap_hw, row_top))
                # Bottom cap
                painter.drawLine(QtCore.QPointF(x - cap_hw, row_bot), QtCore.QPointF(x + cap_hw, row_bot))
                painter.setPen(bm_pen)   # restore dashed pen

                # 🔖 label — anchored to max(bounds_top, visible_top) so it
                # stays on-screen even when bounds extend above the viewport.
                lbl_anchor_y = max(_top_y, y_lo)
                pt_px = t.map(QtCore.QPointF(x, lbl_anchor_y))
                painter.save()
                painter.resetTransform()
                painter.setFont(lbl_font)
                painter.setPen(bm_color)
                painter.drawText(
                    QtCore.QPointF(pt_px.x() + 4, pt_px.y() + 13),
                    "\U0001f516 " + bm["name"],
                )
                painter.restore()
                painter.setPen(bm_pen)

        # ── Bar labels pass (elided function names) ────────────────
        # Toggled via View > Show Function Names on Bars. Off by default.
        if self._show_bar_labels:
            MIN_LABEL_PX = 30
            TEXT_PAD_PX = 4

            painter.save()
            painter.resetTransform()
            painter.setPen(QtGui.QColor(THEME["text_white"]))
            label_font = QtGui.QFont("Segoe UI", self._chart_font_size)
            painter.setFont(label_font)
            fm = painter.fontMetrics()
            label_align = (
                QtCore.Qt.AlignmentFlag.AlignVCenter
                | QtCore.Qt.AlignmentFlag.AlignLeft
            )

            for depth in range(depth_lo, depth_hi + 1):
                lst = self._by_depth.get(depth)
                if not lst:
                    continue
                x0s = self._x0s[depth]
                i_start = max(0, bisect_left(x0s, x_lo) - 1)
                i_end = bisect_right(x0s, x_hi)

                for i in range(i_start, i_end):
                    s = lst[i]
                    if s["name"] in hidden:
                        continue
                    if s["x1"] < x_lo:
                        continue
                    if s["x0"] > x_hi:
                        break

                    # Screen pixel width — skip bars too narrow for any text
                    w_px = (s["x1"] - s["x0"]) * px_per_unit_x
                    if w_px < MIN_LABEL_PX:
                        continue

                    # Map the bar rect to screen coordinates using the
                    # previously-captured transform `t`
                    top_left = t.map(QtCore.QPointF(s["x0"], depth))
                    bot_right = t.map(QtCore.QPointF(s["x1"], depth + self._row_height))
                    text_width_px = bot_right.x() - top_left.x() - 2 * TEXT_PAD_PX
                    if text_width_px < MIN_LABEL_PX - 2 * TEXT_PAD_PX:
                        continue

                    screen_rect = QtCore.QRectF(
                        top_left.x() + TEXT_PAD_PX,
                        top_left.y(),
                        text_width_px,
                        bot_right.y() - top_left.y(),
                    )

                    text = fm.elidedText(
                        s["name"],
                        QtCore.Qt.TextElideMode.ElideRight,
                        int(text_width_px),
                    )
                    painter.drawText(screen_rect, label_align, text)

            painter.restore()

        # ── Sticky hover label pass (dark pill, top-left of viewport) ──
        # Toggled via View > Sticky Hover Label. Off by default.
        if self._show_sticky_hover and self._sticky_text:
            painter.save()
            painter.resetTransform()
            pill_font = QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold)
            painter.setFont(pill_font)
            fm2 = painter.fontMetrics()
            pad = 8
            tw = fm2.horizontalAdvance(self._sticky_text)
            th = fm2.height()
            # Anchor at the top-left of the *exposed* viewport so the pill
            # stays glued to the visible area even as the user pans/zooms.
            ex = option.exposedRect
            tl = t.map(QtCore.QPointF(ex.left(), ex.top()))
            x = tl.x() + 10
            y = tl.y() + 10
            pill = QtCore.QRectF(x, y, tw + 2 * pad, th + 2 * pad)
            painter.setPen(QtGui.QPen(QtGui.QColor(THEME["scroll_handle_hover"]), 1))
            pill_bg = QtGui.QColor(THEME["bg_elevated"])
            pill_bg.setAlpha(220)
            painter.setBrush(pill_bg)
            painter.drawRoundedRect(pill, 4, 4)
            painter.setPen(QtGui.QColor(THEME["text_primary"]))
            painter.drawText(
                pill,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                self._sticky_text,
            )
            painter.restore()
