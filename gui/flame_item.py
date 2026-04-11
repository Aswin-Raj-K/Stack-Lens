"""Flame-chart graphics item: fast, culled, solid-block renderer."""

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .constants import ROW_HEIGHT, VIRIDIS


class FlameItem(pg.GraphicsObject):
    """Flame chart with viewport culling, solid blocks, two color modes,
    ISR lane rendering, and timeline marks.

    Display coordinate system (Y, with pyqtgraph invertY=True so smaller y
    appears higher on screen):
        - Thread spans:  display_y = depth                  (0, 1, 2, ...)
        - ISR spans:     display_y = -(depth + 1)           (-1, -2, -3, ...)
                         so they appear ABOVE the thread lanes.
    """

    def __init__(self, spans, color_map, t_min, color_mode="function", marks=None, pause_regions=None):
        super().__init__()
        self._t_min = t_min
        self._color_mode = color_mode
        self._hidden = set()
        self._hidden_marks = set()  # set of marker names to skip drawing
        self._highlighted_name = None
        self._pause_regions = []  # list of {x0, x1} (relative)
        self._show_bar_labels = False  # toggled via View menu — off by default
        self._show_sticky_hover = False  # sticky top-left hover label
        self._sticky_text = ""

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

            fn_color = QtGui.QColor(color_map.get(sp["name"], "#888"))

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
        return QtGui.QColor("#888888")

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
            pause_fill = QtGui.QColor(110, 110, 120, 90)   # neutral gray
            edge_pen = QtGui.QPen(QtGui.QColor("#aaaaaa"))
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
                rect = QtCore.QRectF(s["x0"], depth, draw_w, ROW_HEIGHT)

                if hl is not None and s["name"] != hl:
                    painter.fillRect(rect, s[dim_key])
                else:
                    painter.fillRect(rect, s[color_key])

        # ── Pause regions: dim overlay + 'PAUSED' label on top of bars ──
        if self._pause_regions:
            top_y_full = self._bounds.top()
            bot_y_full = self._bounds.bottom()
            overlay = QtGui.QColor(30, 30, 35, 110)  # neutral dark dim
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
            painter.setPen(QtGui.QColor("#dddddd"))
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

            # Bright cyan line — much more visible than faint white
            line_pen = QtGui.QPen(QtGui.QColor("#00ddff"))
            line_pen.setWidth(2)
            line_pen.setCosmetic(True)  # 2 pixels regardless of zoom
            painter.setPen(line_pen)

            mark_color = QtGui.QColor("#00ddff")
            flag_height = 0.35  # data units, placed just below top_y

            hidden_marks = self._hidden_marks
            for i in range(i_lo, i_hi):
                m = self._marks[i]
                if m["name"] in hidden_marks:
                    continue
                x = m["x"]
                if x < x_lo - margin or x > x_hi + margin:
                    continue
                # Vertical line through entire chart
                painter.drawLine(QtCore.QPointF(x, top_y), QtCore.QPointF(x, bot_y))

                # Small filled triangle at the top for extra visibility
                tri = QtGui.QPolygonF([
                    QtCore.QPointF(x, top_y),
                    QtCore.QPointF(x - 0.3 / px_per_unit_x * 6, top_y - flag_height),
                    QtCore.QPointF(x + 0.3 / px_per_unit_x * 6, top_y - flag_height),
                ])
                painter.setBrush(QtGui.QBrush(mark_color))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawPolygon(tri)
                painter.setPen(line_pen)

        # ── Bar labels pass (elided function names) ────────────────
        # Toggled via View > Show Function Names on Bars. Off by default.
        if self._show_bar_labels:
            MIN_LABEL_PX = 30
            TEXT_PAD_PX = 4

            painter.save()
            painter.resetTransform()
            painter.setPen(QtGui.QColor("#ffffff"))
            label_font = QtGui.QFont("Segoe UI", 8)
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
                    bot_right = t.map(QtCore.QPointF(s["x1"], depth + ROW_HEIGHT))
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
            painter.setPen(QtGui.QPen(QtGui.QColor("#5a5a70"), 1))
            painter.setBrush(QtGui.QColor(15, 15, 20, 220))
            painter.drawRoundedRect(pill, 4, 4)
            painter.setPen(QtGui.QColor("#ffffff"))
            painter.drawText(
                pill,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                self._sticky_text,
            )
            painter.restore()
