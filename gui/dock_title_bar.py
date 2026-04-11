"""Custom title bar for QDockWidget with clearly styled close/float buttons.

Replaces Qt's default title bar (whose buttons are barely visible with the
dark theme on Windows). Uses standard style icons at 16x16 inside obvious
button backgrounds.
"""

from PySide6 import QtCore, QtGui, QtWidgets


class DockTitleBar(QtWidgets.QWidget):
    """Custom QDockWidget title bar.

    Qt's default buttons are tiny and nearly invisible against a dark theme.
    This widget draws a simple flat title strip with two prominent square
    buttons on the right.
    """

    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self._dock = dock
        self.setAutoFillBackground(True)
        self.setObjectName("DockTitleBar")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 5, 3)
        layout.setSpacing(4)

        # Title label (left, stretches)
        self.title_label = QtWidgets.QLabel(dock.windowTitle())
        self.title_label.setObjectName("DockTitle")
        layout.addWidget(self.title_label, 1)

        # Float / dock button (middle)
        style = self.style()
        self.float_btn = QtWidgets.QToolButton()
        self.float_btn.setIcon(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TitleBarNormalButton)
        )
        self.float_btn.setIconSize(QtCore.QSize(10, 10))
        self.float_btn.setFixedSize(QtCore.QSize(18, 18))
        self.float_btn.setToolTip("Float / dock")
        self.float_btn.setObjectName("DockFloatBtn")
        self.float_btn.clicked.connect(self._toggle_float)
        layout.addWidget(self.float_btn)

        # Close button (right)
        self.close_btn = QtWidgets.QToolButton()
        self.close_btn.setIcon(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TitleBarCloseButton)
        )
        self.close_btn.setIconSize(QtCore.QSize(10, 10))
        self.close_btn.setFixedSize(QtCore.QSize(18, 18))
        self.close_btn.setToolTip("Close")
        self.close_btn.setObjectName("DockCloseBtn")
        self.close_btn.clicked.connect(dock.close)
        layout.addWidget(self.close_btn)

        # Keep the label in sync if the dock's title changes
        dock.windowTitleChanged.connect(self.title_label.setText)

    def _toggle_float(self):
        self._dock.setFloating(not self._dock.isFloating())
