"""GUI constants: color palette, stylesheet, layout sizes."""

COLORS = [
    "#4C78A8", "#F58518", "#E45756", "#72B7B2", "#54A24B",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC",
    "#D67195", "#B6E880", "#FF97FF", "#FECB52", "#636EFA",
    "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692",
]

# Viridis-like heat colormap, used for "color by duration" mode.
# Cold (dark purple) = fast, hot (yellow) = slow.
VIRIDIS = [
    "#440154", "#481A6C", "#472F7D", "#414487", "#39568C",
    "#31688E", "#2A788E", "#23888E", "#1F988B", "#22A884",
    "#35B779", "#54C568", "#7AD151", "#A5DB36", "#D2E21B",
    "#FDE725",
]

DARK_STYLESHEET = """
QMainWindow, QWidget { background: #181820; color: #e0e0e0; }
QLabel { color: #e0e0e0; }
QPushButton {
    background: #2a2a36; color: #d8d8f0; border: 1px solid #505068;
    padding: 4px 12px; border-radius: 3px;
}
QPushButton:hover { background: #353548; }
QPushButton:pressed { background: #1f1f2a; }
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background: #22222c; color: #e0e0e0; border: 1px solid #484860;
    padding: 3px; border-radius: 3px;
}
QToolBar {
    background: #1f1f2a;
    border: none;
    border-bottom: 1px solid #2a2a3c;
    spacing: 6px;
    padding: 4px 6px;
}
/* Labels are muted so they read as field captions, not values.
   transparent background lets the toolbar colour show through. */
QToolBar QLabel { background: transparent; color: #7878a0; }
QHeaderView { background: #1f1f2a; }
QHeaderView::section {
    background: #2a2a36;
    color: #e0e0e0;
    /* Extra right padding reserves space for the SortableHeader overlay arrow.
       SortableHeader draws the ▲/▼ glyph ~18 px from the right edge, so 22 px
       of right padding keeps text clear of the indicator. */
    padding: 6px 22px 6px 10px;
    border: 0;
    border-right: 1px solid #1f1f2a;
    font-weight: bold;
}
QHeaderView::section:hover {
    background: #3d3d52;
    color: #ffffff;
}
QHeaderView::section:pressed {
    background: #4C78A8;
}
QHeaderView::section:last {
    border-right: none;
}
QWidget#DockCtrlPanel {
    background: #252535;
    border-bottom: 1px solid #1a1a28;
}
QWidget#DockCtrlPanel QLabel { background: transparent; color: #7878a0; }
QWidget#DockCtrlPanel QPushButton {
    background: #2e2e42; border-color: #505068; padding: 3px 10px;
}
QWidget#DockCtrlPanel QPushButton:hover { background: #3a3a52; }
QWidget#DockCtrlPanel QPushButton:pressed { background: #1e1e30; }
QWidget#DockCtrlPanel QLineEdit, QWidget#DockCtrlPanel QSpinBox {
    background: #1e1e2c; border-color: #505068;
}
QTableWidget { background: #1f1f2a; gridline-color: #2a2a36; alternate-background-color: #22222c; }
/* Dock title bar is a custom widget (DockTitleBar); style via object name */
QWidget#DockTitleBar {
    background: #2e2e3c;
    border-bottom: 1px solid #1f1f2a;
}
QLabel#DockTitle {
    color: #ffffff;
    font-weight: bold;
    font-size: 11pt;
    background: transparent;
}
QToolButton#DockCloseBtn, QToolButton#DockFloatBtn {
    background: #4a4a5a;
    border: 1px solid #6a6a85;
    border-radius: 3px;
}
QToolButton#DockCloseBtn:hover, QToolButton#DockFloatBtn:hover {
    background: #7a7aa0;
    border: 1px solid #a0a0c0;
}
QToolButton#DockCloseBtn:pressed, QToolButton#DockFloatBtn:pressed {
    background: #9a9ac0;
}
QScrollBar:horizontal {
    background: #22222c;
    height: 16px;
    border: none;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #4a4a5a;
    min-width: 40px;
    border-radius: 6px;
    margin: 2px 2px;
}
QScrollBar::handle:horizontal:hover { background: #5a5a70; }
QScrollBar::handle:horizontal:pressed { background: #6a6a85; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0; height: 0; background: none; border: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: #22222c;
}
QScrollBar:vertical {
    background: #22222c;
    width: 16px;
    border: none;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4a4a5a;
    min-height: 40px;
    border-radius: 6px;
    margin: 2px 2px;
}
QScrollBar::handle:vertical:hover { background: #5a5a70; }
QScrollBar::handle:vertical:pressed { background: #6a6a85; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    width: 0; height: 0; background: none; border: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: #22222c;
}
QScrollBar::corner { background: #22222c; }
QStatusBar { background: #1f1f2a; color: #aaa; }

/* Dock tab styling — make unselected tabs readable */
QTabBar::tab {
    background: #252535;
    color: #9090b8;
    padding: 6px 16px;
    border: 1px solid #1a1a28;
    border-bottom: none;
    margin-right: 2px;
    min-width: 90px;
}
QTabBar::tab:selected {
    background: #3d3d52;
    color: #ffffff;
    font-weight: bold;
    border: 1px solid #3a3a52;
    border-bottom: 2px solid #4C78A8;
}
QTabBar::tab:hover:!selected {
    background: #2e2e44;
    color: #d0d0f0;
}
QTreeWidget {
    background: #1f1f2a; gridline-color: #2a2a36;
    alternate-background-color: #22222c;
}
QTreeWidget::item:selected { background: #3d3d52; }

/* QListView — used by QCompleter popups and other list widgets */
QListView {
    background: #22222c;
    color: #e0e0e0;
    border: 1px solid #3a3a4a;
    outline: 0;
    selection-background-color: #3d3d52;
    selection-color: #ffffff;
}
QListView::item {
    padding: 5px 10px;
    border: 0;
}
QListView::item:selected {
    background: #3d3d52;
    color: #ffffff;
}
QListView::item:hover {
    background: #2a2a36;
}

/* QComboBox popup (dropdown arrow) — separate from QCompleter popup */
QComboBox QAbstractItemView {
    background: #22222c;
    color: #e0e0e0;
    border: 1px solid #3a3a4a;
    outline: 0;
    selection-background-color: #3d3d52;
    selection-color: #ffffff;
}

/* Minimap strip separator is drawn in MinimapWidget.paintEvent — the
   stylesheet border-bottom doesn't apply to widgets with a custom
   paintEvent that fills their full rect. */

/* Menus — context menus and menubar dropdowns */
QMenu {
    background: #2a2a36;
    color: #e0e0e0;
    border: 1px solid #3a3a4a;
    border-radius: 4px;
    padding: 6px 0;
}
QMenu::item {
    padding: 8px 28px 8px 20px;
    min-width: 200px;
    background: transparent;
}
QMenu::item:selected {
    background: #3d3d52;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #666666;
}
QMenu::separator {
    height: 1px;
    background: #3a3a4a;
    margin: 4px 8px;
}

/* ── Toolbar separator ──────────────────────────────────────── */
QToolBar::separator {
    background: #3a3a52;
    width: 1px;
    margin: 4px 6px;
}

/* ── Toolbar action buttons (Go / Next / Zoom to Selection) ─── */
QToolBar QToolButton {
    background: #252535;
    color: #c0c0d8;
    border: 1px solid #3e3e56;
    border-radius: 4px;
    padding: 3px 12px;
    min-width: 40px;
}
QToolBar QToolButton:hover {
    background: #2e2e48;
    border-color: #585880;
    color: #e8e8ff;
}
QToolBar QToolButton:pressed {
    background: #1a1a2e;
    border-color: #3a3a58;
    color: #ffffff;
}
QToolBar QToolButton:checked {
    background: #1a2d50;
    border: 1px solid #4880b8;
    color: #80c0ff;
    font-weight: bold;
}
QToolBar QToolButton:checked:hover {
    background: #1f3868;
    border-color: #60a0d8;
    color: #a8d8ff;
}

/* ── Toolbar input fields ────────────────────────────────────── */
/* Brighter border so the fields are clearly legible against the toolbar. */
QToolBar QDoubleSpinBox, QToolBar QSpinBox, QToolBar QComboBox {
    border-color: #505068;
}
QToolBar QDoubleSpinBox:focus, QToolBar QSpinBox:focus, QToolBar QComboBox:focus {
    border-color: #4C78A8;
}
"""

# Flame-chart geometry
ROW_HEIGHT = 0.85           # data units (out of 1.0 row)
DEFAULT_WINDOW_US = 1000.0  # default visible time window in microseconds (= 1 ms)
