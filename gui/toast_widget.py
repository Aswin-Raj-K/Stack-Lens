"""Bottom-right floating notification widget with slide animation.

Levels:
    "error"   — red,   stays until dismissed
    "warning" — amber, auto-dismisses after 6 s
    "info"    — blue,  auto-dismisses after 4 s
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .theme import THEME


class ToastWidget(QtWidgets.QWidget):
    """Modern rounded-card toast pinned to the bottom-right of its parent."""

    _LEVEL_ACCENT = {
        "error":   "#e05555",
        "warning": "#d4920a",
        "info":    "#4a90d9",
    }
    _AUTO_DISMISS_MS = {
        "error":   0,
        "warning": 6000,
        "info":    4000,
    }
    _WIDTH  = 320
    _RADIUS = 4
    _MARGIN = 16

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFixedWidth(self._WIDTH)

        # ── auto-dismiss timer ─────────────────────────────────────────
        self._dismiss_timer = QtCore.QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._start_slide_out)

        # ── progress-bar drain timer (updates every 50 ms) ────────────
        self._progress_timer = QtCore.QTimer(self)
        self._progress_timer.setInterval(50)
        self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_total_ms = 0
        self._progress_elapsed_ms = 0

        # ── slide animation ────────────────────────────────────────────
        self._anim = QtCore.QPropertyAnimation(self, b"geometry")
        self._anim.finished.connect(self._on_anim_finished)
        self._sliding_out = False

        # ── layout ────────────────────────────────────────────────────
        self._accent_color = QtGui.QColor(self._LEVEL_ACCENT["info"])
        self._progress_frac = 1.0   # 1.0 = full, 0.0 = empty

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QtWidgets.QWidget()
        card.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setObjectName("ToastCard")
        root.addWidget(card)

        row = QtWidgets.QHBoxLayout(card)
        row.setContentsMargins(14, 12, 10, 14)
        row.setSpacing(10)

        # Icon dot
        self._icon_lbl = QtWidgets.QLabel("\u25cf")
        self._icon_lbl.setFixedWidth(14)
        self._icon_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter
        )
        self._icon_lbl.setStyleSheet("background: transparent; font-size: 10pt;")
        row.addWidget(self._icon_lbl)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(3)
        self._title_lbl = QtWidgets.QLabel()
        self._title_lbl.setWordWrap(False)
        self._title_lbl.setStyleSheet("background: transparent; font-weight: 600; font-size: 10pt;")
        self._msg_lbl = QtWidgets.QLabel()
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet("background: transparent; font-size: 9pt;")
        text_col.addWidget(self._title_lbl)
        text_col.addWidget(self._msg_lbl)
        row.addLayout(text_col, 1)

        # Close button
        close_btn = QtWidgets.QToolButton()
        close_btn.setText("\u00d7")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "QToolButton{border:none;color:#888;font-size:14px;background:transparent;}"
            "QToolButton:hover{color:#fff;}"
        )
        close_btn.clicked.connect(self._start_slide_out)
        row.addWidget(close_btn)

        self.hide()

    # ── Public API ───────────────────────────────────────────────────

    def show_message(self, title: str, message: str, level: str = "warning") -> None:
        self._dismiss_timer.stop()
        self._progress_timer.stop()
        self._sliding_out = False

        accent_hex = self._LEVEL_ACCENT.get(level, self._LEVEL_ACCENT["info"])
        self._accent_color = QtGui.QColor(accent_hex)

        bg    = THEME.get("bg_elevated", "#1e1e28")
        txt   = THEME.get("text_primary", "#e8e8f0")
        muted = THEME.get("text_muted", "#9090a8")

        self.findChild(QtWidgets.QWidget, "ToastCard").setStyleSheet(
            f"QWidget#ToastCard {{"
            f"  background: {bg};"
            f"  border: 1px solid {accent_hex}44;"
            f"  border-radius: {self._RADIUS}px;"
            f"}}"
        )
        self._icon_lbl.setStyleSheet(
            f"background:transparent; font-size:10pt; color:{accent_hex};"
        )
        self._title_lbl.setStyleSheet(
            f"background:transparent; font-weight:600; font-size:10pt; color:{txt};"
        )
        self._msg_lbl.setStyleSheet(
            f"background:transparent; font-size:9pt; color:{muted};"
        )
        self._title_lbl.setText(title)
        self._msg_lbl.setText(message)

        delay = self._AUTO_DISMISS_MS.get(level, 4000)
        self._progress_total_ms   = delay
        self._progress_elapsed_ms = 0
        self._progress_frac       = 1.0

        self.adjustSize()
        self._start_slide_in()

        if delay:
            self._dismiss_timer.start(delay)
            self._progress_timer.start()

    # ── Animation ────────────────────────────────────────────────────

    def _rest_geometry(self) -> QtCore.QRect:
        """Geometry of the toast when fully visible (bottom-right of parent)."""
        p = self.parent()
        if not isinstance(p, QtWidgets.QWidget):
            return self.geometry()
        x = p.width() - self.width() - self._MARGIN
        y = p.height() - self.height() - self._MARGIN - 28
        return QtCore.QRect(max(0, x), max(0, y), self.width(), self.height())

    def _offscreen_geometry(self) -> QtCore.QRect:
        """Geometry just off the right edge of the parent."""
        g = self._rest_geometry()
        p = self.parent()
        off_x = p.width() + 10 if isinstance(p, QtWidgets.QWidget) else g.x() + self.width() + 20
        return QtCore.QRect(off_x, g.y(), g.width(), g.height())

    def _start_slide_in(self):
        self._anim.stop()
        rest = self._rest_geometry()
        off  = self._offscreen_geometry()
        self.setGeometry(off)
        self.show()
        self.raise_()
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(off)
        self._anim.setEndValue(rest)
        self._anim.start()

    def _start_slide_out(self):
        self._dismiss_timer.stop()
        self._progress_timer.stop()
        self._sliding_out = True
        rest = self._rest_geometry()
        off  = self._offscreen_geometry()
        self._anim.stop()
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
        self._anim.setStartValue(rest)
        self._anim.setEndValue(off)
        self._anim.start()

    def _on_anim_finished(self):
        if self._sliding_out:
            self.hide()
            self._sliding_out = False

    # ── Progress drain ───────────────────────────────────────────────

    def _tick_progress(self):
        self._progress_elapsed_ms += 50
        if self._progress_total_ms > 0:
            self._progress_frac = max(
                0.0, 1.0 - self._progress_elapsed_ms / self._progress_total_ms
            )
        self.update()

    # ── Painting ─────────────────────────────────────────────────────

    def paintEvent(self, _event):
        if self._progress_total_ms <= 0 or self._progress_frac <= 0:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        bar_h = 3
        w = int(self.width() * self._progress_frac)
        y = self.height() - bar_h
        color = QtGui.QColor(self._accent_color)
        color.setAlpha(180)
        p.fillRect(QtCore.QRect(0, y, w, bar_h), color)
        p.end()

    # ── Reposition on parent resize ──────────────────────────────────

    def reposition(self) -> None:
        """Call this from ProfilerWindow.resizeEvent when toast is visible."""
        if self.isVisible() and not self._sliding_out:
            self.setGeometry(self._rest_geometry())
