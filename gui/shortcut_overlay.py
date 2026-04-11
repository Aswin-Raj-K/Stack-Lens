"""Keyboard-shortcut cheat-sheet overlay — shown by pressing ``?``.

A semi-transparent QWidget child of the main window that lists every
shortcut in a grid. Dismissed by any key press or mouse click.
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .theme import FONT_MONO, THEME


# Single source of truth for what's shown. Keep in sync with the actions
# registered in ProfilerWindow._build_menu / _install_pan_zoom_shortcuts.
SHORTCUT_ROWS = [
    ("Navigation", None),
    ("← / →",              "Pan left / right (10%)"),
    ("Shift + ← / →",       "Pan left / right (50%)"),
    ("[ / ]",               "Fine pan (1%)"),
    ("+ / −",               "Zoom in / out"),
    ("Mouse wheel",         "Zoom centred on cursor"),
    ("Home / End",          "Jump to trace start / end"),
    ("Shift + Left-drag",   "Zoom to selected region"),

    ("Find", None),
    ("Ctrl+F",              "Focus Find box"),
    ("F3",                  "Next occurrence"),
    ("Shift+F3",            "Previous occurrence"),

    ("View toggles", None),
    ("Ctrl+L",              "Show function names on bars"),
    ("Ctrl+H",              "Highlight hovered function"),
    ("Ctrl+M",              "Measurement cursors"),
    ("Ctrl+P",              "Pick spans (A→B delta)"),
    ("Ctrl+R",              "Select-zoom mode"),
    ("Ctrl+0",              "Reset view"),
    ("Ctrl+Shift+M",        "Toggle minimap"),

    ("Docks", None),
    ("Ctrl+Shift+F",        "Function Summary dock"),
    ("Ctrl+Shift+T",        "Call Tree dock"),
    ("Ctrl+Shift+K",        "Markers dock"),
    ("Ctrl+Shift+O",        "Top-N Slowest dock"),

    ("File", None),
    ("Ctrl+O",              "Open trace…"),
    ("F5",                  "Refresh"),
    ("Ctrl+Q",              "Quit"),

    ("Misc", None),
    ("?",                   "Show this overlay"),
    ("Esc",                 "Cancel current mode / close overlay"),
]


class ShortcutOverlay(QtWidgets.QWidget):
    """Modal-feeling cheat sheet overlay child of the main window."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        self._panel = QtWidgets.QFrame(self)
        self._panel.setObjectName("ShortcutPanel")
        T = THEME
        self._panel.setStyleSheet(
            f"QFrame#ShortcutPanel {{"
            f"  background: rgba(26, 26, 38, 252);"
            f"  border: 1px solid {T['border_input']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QLabel {{ color: #c8c8e0; background: transparent; }}"
            f"QLabel#ShortcutTitle {{"
            f"  font-size: 13pt; font-weight: bold; color: {T['text_white']};"
            f"}}"
            f"QLabel#SectionHeader {{"
            f"  font-weight: bold; color: {T['accent_checked_text']};"
            f"  padding: 2px 0px;"
            f"}}"
            # Key chip: monospace badge matching the DockCtrlPanel look
            f"QLabel#KeyLabel {{"
            f"  font-family: {FONT_MONO};"
            f"  color: {T['text_primary']}; background: {T['bg_ctrl_panel']};"
            f"  border: 1px solid {T['interactive_ctrl_hover']}; border-radius: 3px;"
            f"  padding: 1px 6px;"
            f"}}"
            f"QLabel#DescLabel {{ color: #9898b8; }}"
            f"QLabel#HintLabel  {{ color: #606080; }}"
            # Thin horizontal rule between sections
            f"QFrame#SectionSep {{"
            f"  color: {T['interactive_hover']}; border: none; border-top: 1px solid {T['interactive_hover']};"
            f"  max-height: 1px;"
            f"}}"
        )

        grid = QtWidgets.QGridLayout(self._panel)
        grid.setContentsMargins(28, 22, 28, 20)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)

        title = QtWidgets.QLabel("Keyboard Shortcuts")
        title.setObjectName("ShortcutTitle")
        grid.addWidget(title, 0, 0, 1, 2)
        grid.addItem(
            QtWidgets.QSpacerItem(1, 6,
                                  QtWidgets.QSizePolicy.Policy.Minimum,
                                  QtWidgets.QSizePolicy.Policy.Fixed),
            1, 0,
        )

        row_idx = 2
        first_section = True
        for key, desc in SHORTCUT_ROWS:
            if desc is None:
                # Separator line before every section except the first
                if not first_section:
                    sep = QtWidgets.QFrame()
                    sep.setObjectName("SectionSep")
                    sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                    sep.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
                    grid.addWidget(sep, row_idx, 0, 1, 2)
                    row_idx += 1
                first_section = False

                header = QtWidgets.QLabel(key)
                header.setObjectName("SectionHeader")
                header.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignLeft
                    | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
                grid.addWidget(header, row_idx, 0, 1, 2)
            else:
                k = QtWidgets.QLabel(key)
                k.setObjectName("KeyLabel")
                k.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignLeft
                    | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
                d = QtWidgets.QLabel(desc)
                d.setObjectName("DescLabel")
                grid.addWidget(k, row_idx, 0)
                grid.addWidget(d, row_idx, 1)
            row_idx += 1

        grid.addItem(
            QtWidgets.QSpacerItem(1, 8,
                                  QtWidgets.QSizePolicy.Policy.Minimum,
                                  QtWidgets.QSizePolicy.Policy.Fixed),
            row_idx, 0,
        )
        hint = QtWidgets.QLabel("Press any key or click to dismiss")
        hint.setObjectName("HintLabel")
        hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(hint, row_idx + 1, 0, 1, 2)

        self.hide()

    # ── Show/dismiss ────────────────────────────────────────────────

    def show_centered(self):
        parent = self.parent()
        if isinstance(parent, QtWidgets.QWidget):
            self.setGeometry(parent.rect())
        self._panel.adjustSize()
        p = self._panel.sizeHint()
        x = (self.width() - p.width()) // 2
        y = (self.height() - p.height()) // 2
        self._panel.move(max(0, x), max(0, y))
        self.show()
        self.raise_()
        self.setFocus()

    # ── Event handlers ──────────────────────────────────────────────

    def keyPressEvent(self, event):
        self.hide()
        event.accept()

    def mousePressEvent(self, event):
        self.hide()
        event.accept()

    def paintEvent(self, event):
        # Full-widget semi-transparent dim layer (the panel paints itself)
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 120))

    def resizeEvent(self, event):
        # Re-centre the panel if parent resized while we're visible
        if self.isVisible():
            parent = self.parent()
            if isinstance(parent, QtWidgets.QWidget):
                self.setGeometry(parent.rect())
            p = self._panel.sizeHint()
            x = (self.width() - p.width()) // 2
            y = (self.height() - p.height()) // 2
            self._panel.move(max(0, x), max(0, y))
        super().resizeEvent(event)
