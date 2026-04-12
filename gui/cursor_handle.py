"""Draggable grab-tab handles for measurement cursors.

CursorHandle is a fixed-pixel-size pyqtgraph GraphicsObject pinned to the top
of a measurement InfiniteLine.  It lets users grab and drag cursors without
having to hit the 2 px line itself.
"""

import pyqtgraph as pg
from PySide6 import QtCore, QtGui


class CursorHandle(pg.GraphicsObject):
    """Fixed-pixel-size grab tab drawn at the top of a measurement cursor line.

    Positioned in data coordinates at (cursor.value(), viewRect.top()).
    Painted in screen-pixel coordinates so the tab never changes visual size
    when the user zooms the time axis.
    Dragging the tab moves the parent InfiniteLine horizontally.
    """

    _HW = 7   # half-width of the rectangle base, in pixels
    _HR = 9   # height of the rectangle base, in pixels
    _HT = 6   # height of the triangular tip, in pixels

    def __init__(self, cursor: pg.InfiniteLine, color: str):
        super().__init__()
        self._cursor = cursor
        self._brush = pg.mkBrush(color)
        self._hover_brush = pg.mkBrush(QtGui.QColor(color).lighter(140))
        self._pen = pg.mkPen(QtGui.QColor(color).darker(150), width=1)
        self._hovered = False
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setZValue(200)

    # ── Qt geometry ──────────────────────────────────────────────────

    def boundingRect(self) -> QtCore.QRectF:
        vb = self.getViewBox()
        if vb is None:
            return QtCore.QRectF(-1, -0.1, 2, 0.5)
        ps = vb.viewPixelSize()
        if ps[0] is None or ps[0] == 0:
            return QtCore.QRectF(-1, -0.1, 2, 0.5)
        x_pp, y_pp = ps
        hw = (self._HW + 2) * x_pp
        hh = (self._HR + self._HT + 2) * abs(y_pp)
        return QtCore.QRectF(-hw, 0, hw * 2, hh)

    def shape(self) -> QtGui.QPainterPath:
        p = QtGui.QPainterPath()
        p.addRect(self.boundingRect())
        return p

    # ── Painting ─────────────────────────────────────────────────────

    def paint(self, painter, option, widget=None):
        # Map the item's origin (data position) to screen pixel coordinates.
        # painter.transform() is the full item-local → device transform, so
        # mapping (0, 0) gives the on-screen pixel position of this handle.
        origin = painter.transform().map(QtCore.QPointF(0, 0))
        painter.save()
        painter.resetTransform()          # switch to raw device (pixel) coords
        painter.translate(origin)         # move origin to handle's screen position
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._hover_brush if self._hovered else self._brush)
        painter.setPen(self._pen)
        hw, hr, ht = self._HW, self._HR, self._HT
        # Rectangle base with a downward-pointing triangular tip (pentagon)
        path = QtGui.QPainterPath()
        path.moveTo(-hw, 0)
        path.lineTo( hw, 0)
        path.lineTo( hw, hr)
        path.lineTo(  0, hr + ht)
        path.lineTo(-hw, hr)
        path.closeSubpath()
        painter.drawPath(path)
        painter.restore()

    # ── Mouse interaction ────────────────────────────────────────────

    def hoverEvent(self, ev):
        changed = False
        if not ev.isExit():
            if not self._hovered:
                self._hovered = True
                self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
                changed = True
        else:
            if self._hovered:
                self._hovered = False
                self.unsetCursor()
                changed = True
        if changed:
            self.update()

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        vb = self.getViewBox()
        if vb:
            x = vb.mapSceneToView(ev.scenePos()).x()
            self._cursor.setPos(x)
        ev.accept()
