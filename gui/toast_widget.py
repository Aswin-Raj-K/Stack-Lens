"""Bottom-right floating notification widget.

Usage (inside ProfilerWindow):
    self._toast = ToastWidget(self)
    self._toast.show_message("Validation warning", "spans[3] missing depth field",
                             level="warning")

Levels:
    "error"   — red accent, stays until dismissed
    "warning" — amber accent, auto-dismisses after 6 s
    "info"    — blue accent, auto-dismisses after 4 s
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .theme import THEME


class ToastWidget(QtWidgets.QWidget):
    """Single-message bottom-right toast.  Replaces itself on each call."""

    _LEVEL_COLORS = {
        "error":   ("#e05555", "#2a1010"),
        "warning": ("#e0a020", "#1e1800"),
        "info":    ("#4a90d9", "#0d1a2a"),
    }
    _AUTO_DISMISS_MS = {
        "error":   0,      # never
        "warning": 6000,
        "info":    4000,
    }
    _WIDTH  = 340
    _MARGIN = 14   # gap from window edge

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ToastWidget")

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Coloured left accent bar
        self._bar = QtWidgets.QFrame()
        self._bar.setFixedWidth(4)
        outer.addWidget(self._bar)

        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 8, 8)
        body_layout.setSpacing(2)

        self._title_lbl = QtWidgets.QLabel()
        self._title_lbl.setWordWrap(False)
        self._msg_lbl = QtWidgets.QLabel()
        self._msg_lbl.setWordWrap(True)
        body_layout.addWidget(self._title_lbl)
        body_layout.addWidget(self._msg_lbl)
        outer.addWidget(body, 1)

        # Close button
        close_btn = QtWidgets.QToolButton()
        close_btn.setText("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "QToolButton { border: none; color: #aaa; font-size: 15px;"
            " background: transparent; }"
            "QToolButton:hover { color: #fff; }"
        )
        close_btn.clicked.connect(self.hide)
        outer.addWidget(close_btn)

        self.setFixedWidth(self._WIDTH)
        self.hide()

    # ── Public API ───────────────────────────────────────────────────

    def show_message(self, title: str, message: str, level: str = "warning") -> None:
        """Display the toast.  *level* is ``'error'``, ``'warning'``, or ``'info'``."""
        self._timer.stop()

        accent, bg = self._LEVEL_COLORS.get(level, self._LEVEL_COLORS["info"])
        self._bar.setStyleSheet(f"background: {accent}; border: none;")
        self.setStyleSheet(
            f"QWidget#ToastWidget {{ background: {bg};"
            f" border: 1px solid {accent}; border-left: none;"
            f" border-radius: 0px 4px 4px 0px; }}"
        )
        text_color = THEME.get("text_primary", "#e0e0e0")
        muted_color = THEME.get("text_muted", "#a0a0b0")
        self._title_lbl.setStyleSheet(
            f"font-weight: bold; background: transparent; color: {text_color};"
        )
        self._msg_lbl.setStyleSheet(
            f"background: transparent; color: {muted_color}; font-size: 9pt;"
        )
        self._title_lbl.setText(title)
        self._msg_lbl.setText(message)

        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

        delay = self._AUTO_DISMISS_MS.get(level, 4000)
        if delay:
            self._timer.start(delay)

    # ── Internal ─────────────────────────────────────────────────────

    def _reposition(self) -> None:
        parent = self.parent()
        if not isinstance(parent, QtWidgets.QWidget):
            return
        pw, ph = parent.width(), parent.height()
        x = pw - self.width() - self._MARGIN
        y = ph - self.height() - self._MARGIN - 28  # 28 ≈ status bar height
        self.move(max(0, x), max(0, y))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._reposition()
