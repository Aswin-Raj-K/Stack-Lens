"""Horizontal gradient legend for 'Color by Duration' mode."""

from PySide6 import QtCore, QtGui, QtWidgets

from .constants import VIRIDIS
from .theme import THEME


class ColorBarWidget(QtWidgets.QWidget):
    """A thin horizontal gradient strip with min/max labels.

    Shown when the flame chart is in 'duration' color mode.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._d_min_us = 0.0
        self._d_max_us = 0.0
        self._unit_label = "us"
        self._unit_scale = 1.0

    def set_range(self, d_min_us, d_max_us, unit_label, unit_scale):
        self._d_min_us = d_min_us
        self._d_max_us = d_max_us
        self._unit_label = unit_label
        self._unit_scale = unit_scale
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        # Background
        p.fillRect(self.rect(), QtGui.QColor(THEME["bg_raised"]))

        if self._d_max_us <= 0 or self._d_min_us < 0:
            p.setPen(QtGui.QColor(THEME["text_disabled"]))
            p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "No duration data")
            return

        w = self.width()
        h = self.height()

        # Labels
        label_min = f"{self._d_min_us * self._unit_scale:.3f} {self._unit_label}"
        label_max = f"{self._d_max_us * self._unit_scale:.3f} {self._unit_label}"
        label_title = "Color by duration (log scale)"

        fm = p.fontMetrics()
        label_min_w = fm.horizontalAdvance(label_min) + 12
        label_max_w = fm.horizontalAdvance(label_max) + 12
        title_w = fm.horizontalAdvance(label_title) + 20

        # Gradient rect leaves space for labels on both sides
        grad_x = label_min_w
        grad_right_x = w - label_max_w
        grad_w = max(40, grad_right_x - grad_x)
        grad_rect = QtCore.QRectF(grad_x, 8, grad_w, h - 16)

        grad = QtGui.QLinearGradient(grad_rect.left(), 0, grad_rect.right(), 0)
        n = len(VIRIDIS)
        for i, c in enumerate(VIRIDIS):
            grad.setColorAt(i / max(1, n - 1), QtGui.QColor(c))
        p.fillRect(grad_rect, grad)

        # Thin outline
        pen = QtGui.QPen(QtGui.QColor(THEME["border_normal"]))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRect(grad_rect)

        # Side labels
        p.setPen(QtGui.QColor(THEME["text_primary"]))
        p.drawText(
            QtCore.QRectF(0, 0, label_min_w - 6, h),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            label_min,
        )
        p.drawText(
            QtCore.QRectF(w - label_max_w + 6, 0, label_max_w - 6, h),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            label_max,
        )

        # Title overlaid on gradient if there's room
        if grad_w > title_w + 40:
            p.setPen(QtGui.QColor(THEME["text_white"]))
            p.drawText(
                grad_rect,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                label_title,
            )
