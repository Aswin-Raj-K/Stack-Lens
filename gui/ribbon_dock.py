"""Function Ribbon dock — per-function occurrence timelines.

Each ribbon row is a thin horizontal strip spanning the full trace
time range. One vertical tick per occurrence of the function; tick
height encodes log-scaled duration so outliers stand out. A yellow
viewport overlay (same style as the minimap) tracks the main chart's
current view.

Multiple functions can be pinned simultaneously for visual comparison.
"""

import math

from PySide6 import QtCore, QtGui, QtWidgets


class RibbonRow(QtWidgets.QWidget):
    """One ribbon strip showing all occurrences of a single function."""

    remove_requested = QtCore.Signal(str)           # name
    tick_clicked = QtCore.Signal(str, float)        # name, absolute start_us

    ROW_HEIGHT = 38
    LABEL_WIDTH = 180

    def __init__(self, name, occurrences, color, t_min, total_us,
                 log_dur_min, log_dur_max, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.ROW_HEIGHT)
        self._name = name
        self._occs = occurrences  # list of (start_us, duration_us)
        self._color = QtGui.QColor(color)
        self._t_min = t_min
        self._total_us = max(total_us, 1e-9)
        self._log_dur_min = log_dur_min
        self._log_dur_max = log_dur_max
        self._log_dur_range = max(log_dur_max - log_dur_min, 1e-9)
        self._view_start = t_min
        self._view_end = t_min + total_us
        self._cache = None
        self._cache_size = None
        self.setMouseTracking(True)

        # Layout: [×] [name label] [paint area]. The label is a
        # fixed-width elided QLabel so long function names don't blow
        # out the layout — the full name still shows on hover via tooltip.
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        close_btn = QtWidgets.QToolButton()
        close_btn.setText("×")
        close_btn.setToolTip(f"Remove {name} ribbon")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self._name))
        layout.addWidget(close_btn)

        self._label = QtWidgets.QLabel()
        self._label.setStyleSheet(
            f"color: {self._color.name()}; font-weight: bold; background: transparent;"
        )
        self._label.setFixedWidth(self.LABEL_WIDTH - 30)
        self._label.setToolTip(f"{name}\n{len(occurrences)} calls")
        self._full_label_text = f"{name}  ({len(occurrences)})"
        self._apply_elided_label()
        layout.addWidget(self._label)
        layout.addStretch(1)  # strip paints into the remaining area

    def _apply_elided_label(self):
        fm = self._label.fontMetrics()
        avail = max(0, self._label.width() - 4)
        elided = fm.elidedText(
            self._full_label_text,
            QtCore.Qt.TextElideMode.ElideRight,
            avail,
        )
        self._label.setText(elided)

    # ── Public API ──────────────────────────────────────────────────

    def set_viewport(self, start_us, end_us):
        self._view_start = start_us
        self._view_end = end_us
        self.update()

    # ── Paint ───────────────────────────────────────────────────────

    def _strip_rect(self):
        return QtCore.QRectF(
            self.LABEL_WIDTH,
            2,
            max(1, self.width() - self.LABEL_WIDTH - 4),
            self.height() - 4,
        )

    def _render_cache(self):
        r = self._strip_rect()
        w = max(1, int(r.width()))
        h = max(1, int(r.height()))
        pm = QtGui.QPixmap(w, h)
        pm.fill(QtGui.QColor("#181820"))
        if self._occs:
            p = QtGui.QPainter(pm)
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
            x_scale = w / self._total_us
            pen = QtGui.QPen(self._color)
            pen.setWidth(1)
            p.setPen(pen)
            for start_us, dur in self._occs:
                x = (start_us - self._t_min) * x_scale
                if dur > 0:
                    log_d = math.log10(max(dur, 1e-9))
                    t = (log_d - self._log_dur_min) / self._log_dur_range
                    t = max(0.0, min(1.0, t))
                else:
                    t = 0.0
                tick_h = 4 + int(t * (h - 8))
                y0 = h - tick_h - 2
                p.drawLine(int(x), y0, int(x), y0 + tick_h)
            p.end()
        self._cache = pm
        self._cache_size = (w, h)

    def paintEvent(self, event):
        r = self._strip_rect()
        w, h = int(r.width()), int(r.height())
        if self._cache is None or self._cache_size != (w, h):
            self._render_cache()
        p = QtGui.QPainter(self)
        p.drawPixmap(int(r.left()), int(r.top()), self._cache)
        # Border around the strip so rows look distinct
        border = QtGui.QPen(QtGui.QColor("#3a3a4a"))
        border.setWidth(1)
        p.setPen(border)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        # Viewport overlay — same yellow as the minimap
        if self._total_us > 0:
            x_scale = r.width() / self._total_us
            vx1 = r.left() + (self._view_start - self._t_min) * x_scale
            vx2 = r.left() + (self._view_end - self._t_min) * x_scale
            vx1 = max(r.left(), min(r.right(), vx1))
            vx2 = max(r.left(), min(r.right(), vx2))
            if vx2 - vx1 < 2:
                vx2 = vx1 + 2
            p.fillRect(
                QtCore.QRectF(vx1, r.top(), vx2 - vx1, r.height()),
                QtGui.QColor(255, 220, 0, 60),
            )
            ov_pen = QtGui.QPen(QtGui.QColor("#ffcc00"))
            ov_pen.setWidth(1)
            p.setPen(ov_pen)
            p.drawRect(QtCore.QRectF(vx1, r.top(), vx2 - vx1 - 1, r.height() - 1))
        p.end()

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        r = self._strip_rect()
        if not r.contains(event.position()):
            return
        if not self._occs:
            return
        x_scale = r.width() / self._total_us
        click_us = self._t_min + (event.position().x() - r.left()) / x_scale
        # Nearest tick by absolute start_us
        best = min(self._occs, key=lambda o: abs(o[0] - click_us))
        self.tick_clicked.emit(self._name, float(best[0]))

    def resizeEvent(self, event):
        self._cache = None
        # Re-elide the label in case the font metrics changed
        self._apply_elided_label()
        super().resizeEvent(event)


class RibbonDock(QtWidgets.QDockWidget):
    """Dock hosting a vertical stack of :class:`RibbonRow` widgets."""

    tick_clicked = QtCore.Signal(str, float)  # name, absolute start_us

    def __init__(self, spans, color_map, t_min, total_us, parent=None):
        super().__init__("Function Ribbons", parent)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)
        self._spans = spans
        self._color_map = color_map
        self._t_min = t_min
        self._total_us = total_us
        self._rows = {}  # name -> RibbonRow

        self._recompute_log_dur()

        # Scroll area so adding many ribbons doesn't push the dock out of shape
        self._container = QtWidgets.QWidget()
        self._layout = QtWidgets.QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(3)

        self._hint = QtWidgets.QLabel(
            "Right-click a function in the Function Summary dock and choose\n"
            '"Show in Ribbon View" to add a timeline strip here.'
        )
        self._hint.setStyleSheet("color: #888; padding: 16px; background: transparent;")
        self._hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._hint)
        self._layout.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self._container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setWidget(scroll)

    # ── Public API ──────────────────────────────────────────────────

    def add_function(self, name):
        """Pin a new function's ribbon row. No-op if already present."""
        if name in self._rows:
            return
        occs = [(sp["start_us"], sp["duration_us"])
                for sp in self._spans if sp["name"] == name]
        if not occs:
            return
        color = self._color_map.get(name, "#888")
        row = RibbonRow(
            name, occs, color,
            self._t_min, self._total_us,
            self._log_dur_min, self._log_dur_max,
        )
        row.set_viewport(self._view_start, self._view_end)
        row.remove_requested.connect(self.remove_function)
        row.tick_clicked.connect(self.tick_clicked.emit)
        # Insert above the trailing stretch item
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._rows[name] = row
        self._hint.setVisible(False)

    def remove_function(self, name):
        row = self._rows.pop(name, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        if not self._rows:
            self._hint.setVisible(True)

    def set_viewport(self, start_us, end_us):
        """Mirror the main chart's current view range on every row."""
        self._view_start = start_us
        self._view_end = end_us
        for row in self._rows.values():
            row.set_viewport(start_us, end_us)

    def set_data(self, spans, color_map, t_min, total_us):
        """Called on trace refresh — rebuilds existing ribbons with fresh data."""
        self._spans = spans
        self._color_map = color_map
        self._t_min = t_min
        self._total_us = max(total_us, 1e-9)
        self._recompute_log_dur()
        # Rebuild every pinned row so it picks up new occurrences
        pinned = list(self._rows.keys())
        for n in pinned:
            self.remove_function(n)
        for n in pinned:
            self.add_function(n)

    # ── Internals ───────────────────────────────────────────────────

    def _recompute_log_dur(self):
        durs = [sp["duration_us"] for sp in self._spans if sp["duration_us"] > 0]
        if durs:
            self._log_dur_min = math.log10(min(durs))
            self._log_dur_max = math.log10(max(durs))
        else:
            self._log_dur_min = 0.0
            self._log_dur_max = 1.0
        self._view_start = getattr(self, "_view_start", self._t_min)
        self._view_end = getattr(self, "_view_end", self._t_min + self._total_us)
