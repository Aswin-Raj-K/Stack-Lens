"""Minimap widget — low-res overview of the entire trace with a viewport marker.

Renders all spans once into a QPixmap cache for speed (131K spans takes
~80ms once, then repaint is a cheap pixmap blit + overlay rect).
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .theme import THEME, CANVAS_PAUSE_RGBA


class MinimapWidget(QtWidgets.QWidget):
    """Compact full-trace overview with a draggable viewport indicator.

    Signals:
        view_start_changed(float) — user clicked/dragged; emit new absolute
                                     view_start in microseconds.
    """

    view_start_changed = QtCore.Signal(float)

    def __init__(self, spans, marks, color_map, t_min, total_us, pause_regions=None, parent=None):
        super().__init__(parent)
        self.setObjectName("MinimapWidget")  # matches stylesheet selector
        self.setFixedHeight(70)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QtGui.QColor(THEME["bg_base"]))
        self.setPalette(pal)

        self._cache = None          # QPixmap cache, invalidated on resize/data
        self._cache_size = None
        self._dragging = False
        self._hidden_marks = set()
        self._pause_regions = list(pause_regions or [])

        # Current viewport (in absolute microseconds, same coord system as spans)
        self._view_start_us = t_min
        self._view_end_us = t_min + total_us

        self.set_data(spans, marks, color_map, t_min, total_us, pause_regions)

    # ── Public API ──────────────────────────────────────────────────

    def set_data(self, spans, marks, color_map, t_min, total_us, pause_regions=None):
        """Replace the underlying trace data. Invalidates the cache."""
        self._spans = spans
        self._marks = marks or []
        self._color_map = color_map
        self._t_min = t_min
        self._total_us = max(total_us, 1e-9)
        if pause_regions is not None:
            self._pause_regions = list(pause_regions)

        # Determine display-y range the same way FlameItem does
        min_y = 0
        max_y = 0
        has_isr = False
        for sp in spans:
            d = sp["depth"]
            if sp.get("ipsr", 0) == 0:
                if d > max_y:
                    max_y = d
            else:
                has_isr = True
                y = -(d + 1)
                if y < min_y:
                    min_y = y
        self._min_display_y = min_y
        self._max_display_y = max_y
        self._has_isr = has_isr

        self._invalidate_cache()
        self.update()

    def set_viewport(self, start_us, end_us):
        """Update the overlay rectangle indicating the main view's extent."""
        self._view_start_us = start_us
        self._view_end_us = end_us
        self.update()  # overlay only — no cache rebuild

    def set_hidden_marks(self, names):
        """Set of marker names to hide from the minimap."""
        self._hidden_marks = set(names)
        self._invalidate_cache()
        self.update()

    # ── Cache rendering ─────────────────────────────────────────────

    def _invalidate_cache(self):
        self._cache = None
        self._cache_size = None

    def _ensure_cache(self):
        if (
            self._cache is not None
            and self._cache_size == (self.width(), self.height())
        ):
            return
        self._render_cache()

    # Height of the bottom gutter strip (separator area). Reserved out of
    # the cache paint region so marker lines / pause bands / bars never
    # bleed into it.
    _GUTTER_PX = 5

    def _render_cache(self):
        w = max(1, self.width())
        h = max(1, self.height())
        pm = QtGui.QPixmap(w, h)
        pm.fill(QtGui.QColor(THEME["bg_base"]))

        if self._total_us <= 0 or not self._spans:
            self._cache = pm
            self._cache_size = (w, h)
            return

        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        # Clip all cached content to the region ABOVE the gutter so
        # marks, pause bands, and bars can't extend into the separator.
        content_h = max(1, h - self._GUTTER_PX)
        p.setClipRect(QtCore.QRectF(0, 0, w, content_h))

        # Leave a 1px margin top and bottom (of the content region)
        plot_h = content_h - 2
        x_scale = w / self._total_us

        y_range = self._max_display_y - self._min_display_y + 1  # number of lanes
        row_h = plot_h / max(y_range, 1)

        # Pause regions: gray translucent bands UNDER the bars
        if self._pause_regions:
            pause_fill = QtGui.QColor(*CANVAS_PAUSE_RGBA)
            for r in self._pause_regions:
                px0 = (r["start_us"] - self._t_min) * x_scale
                px1 = (r["end_us"] - self._t_min) * x_scale
                bw = max(1.0, px1 - px0)
                p.fillRect(QtCore.QRectF(px0, 0, bw, content_h), pause_fill)

        for sp in self._spans:
            ipsr = sp.get("ipsr", 0)
            if ipsr == 0:
                dy = sp["depth"]
            else:
                dy = -(sp["depth"] + 1)

            x = (sp["start_us"] - self._t_min) * x_scale
            width = max(1.0, (sp["end_us"] - sp["start_us"]) * x_scale)

            # Convert dy (which can be negative for ISR) into a widget Y coord
            y = 1 + (dy - self._min_display_y) * row_h

            color = QtGui.QColor(self._color_map.get(sp["name"], THEME["canvas_fallback"]))
            p.fillRect(QtCore.QRectF(x, y, width, max(1.0, row_h - 0.2)), color)

        # Marks as bright cyan 2-pixel vertical lines (match main chart).
        # Stop at content_h so the lines don't bleed into the gutter.
        if self._marks:
            mark_pen = QtGui.QPen(QtGui.QColor(THEME["status_mark"]))
            mark_pen.setWidth(2)
            p.setPen(mark_pen)
            for m in self._marks:
                if m["name"] in self._hidden_marks:
                    continue
                mx = (m["t_us"] - self._t_min) * x_scale
                p.drawLine(QtCore.QPointF(mx, 0), QtCore.QPointF(mx, content_h))

        p.end()
        self._cache = pm
        self._cache_size = (w, h)

    # ── Qt overrides ────────────────────────────────────────────────

    def resizeEvent(self, event):
        self._invalidate_cache()
        super().resizeEvent(event)

    def paintEvent(self, event):
        self._ensure_cache()
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._cache)

        w = self.width()
        h = self.height()
        content_h = max(1, h - self._GUTTER_PX)

        if self._total_us > 0:
            x_scale = w / self._total_us
            vx1 = (self._view_start_us - self._t_min) * x_scale
            vx2 = (self._view_end_us - self._t_min) * x_scale
            vx1 = max(0, min(w, vx1))
            vx2 = max(0, min(w, vx2))
            if vx2 - vx1 < 2:
                vx2 = vx1 + 2

            # Viewport overlay — also clipped to the content region so the
            # yellow tint doesn't bleed into the separator gutter.
            overlay = QtGui.QColor(THEME["selection"])
            overlay.setAlpha(50)
            p.fillRect(
                QtCore.QRectF(vx1, 0, vx2 - vx1, content_h),
                overlay,
            )
            border = QtGui.QPen(QtGui.QColor(THEME["selection"]))
            border.setWidth(1)
            p.setPen(border)
            p.drawRect(
                QtCore.QRectF(vx1, 0, vx2 - vx1 - 1, content_h - 1)
            )

        # ── Separator gutter ──────────────────────────────────────
        # A recessed strip matching the toolbar/title-bar palette so it
        # feels like part of the window chrome, not a coloured line.
        # Structure (top → bottom, 5 px tall):
        #   1 px  #0d0d14   dark shadow (top bevel)
        #   3 px  #1f1f2a   toolbar-background fill
        #   1 px  #3a3a4a   subtle highlight along the bottom edge
        gutter_top = content_h
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.fillRect(
            QtCore.QRectF(0, gutter_top, w, self._GUTTER_PX),
            QtGui.QColor(THEME["bg_surface"]),
        )
        shadow_pen = QtGui.QPen(QtGui.QColor(THEME["bg_base"]))
        shadow_pen.setWidth(1)
        p.setPen(shadow_pen)
        p.drawLine(0, gutter_top, w, gutter_top)
        hl_pen = QtGui.QPen(QtGui.QColor(THEME["border_normal"]))
        hl_pen.setWidth(1)
        p.setPen(hl_pen)
        p.drawLine(0, h - 1, w, h - 1)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = True
            self._emit_jump_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._emit_jump_from_x(event.position().x())

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = False

    def _emit_jump_from_x(self, px):
        """Center the current viewport on the clicked X and emit the new start."""
        w = self.width()
        if w <= 0 or self._total_us <= 0:
            return
        click_us = self._t_min + (px / w) * self._total_us
        current_width = self._view_end_us - self._view_start_us
        new_start = click_us - current_width / 2
        # Clamp
        new_start = max(self._t_min, min(new_start, self._t_min + self._total_us - current_width))
        self.view_start_changed.emit(float(new_start))
