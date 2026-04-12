"""GUI constants: color palette, stylesheet, layout sizes."""

import pathlib

from .theme import THEME, _ICONS

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

# Template — {{/}} are literal CSS braces; {token} values are injected by
# build_dark_stylesheet().  Every hex value maps to a THEME key.
_DARK_STYLESHEET_TMPL = """
QMainWindow, QWidget {{ background: {bg_base}; color: {text_primary}; }}
QLabel {{ color: {text_primary}; }}
QPushButton {{
    background: {bg_elevated}; color: {text_btn}; border: 1px solid {border_input};
    padding: 4px 12px; border-radius: 3px;
}}
QPushButton:hover {{ background: {interactive_hover}; }}
QPushButton:pressed {{ background: {interactive_pressed}; }}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
    background: {bg_raised}; color: {text_primary}; border: 1px solid {border_strong};
    padding: 3px; border-radius: 3px;
}}
QToolBar {{
    background: {bg_surface};
    border: none;
    border-bottom: 1px solid {border_toolbar};
    spacing: 6px;
    padding: 4px 6px;
}}
/* Labels are muted so they read as field captions, not values.
   transparent background lets the toolbar colour show through. */
QToolBar QLabel {{ background: transparent; color: {text_muted}; }}
QHeaderView {{ background: {bg_surface}; }}
QHeaderView::section {{
    background: {bg_elevated};
    color: {text_primary};
    /* Extra right padding reserves space for the SortableHeader overlay arrow.
       SortableHeader draws the ▲/▼ glyph ~18 px from the right edge, so 22 px
       of right padding keeps text clear of the indicator. */
    padding: 6px 22px 6px 10px;
    border: 0;
    border-right: 1px solid {border_header};
    font-weight: bold;
}}
QHeaderView::section:hover {{
    background: {selection_bg};
    color: {header_hover_text};
}}
QHeaderView::section:pressed {{
    background: {accent_primary};
}}
QHeaderView::section:last {{
    border-right: none;
}}
QWidget#DockCtrlPanel {{
    background: {bg_ctrl_panel};
    border-bottom: 1px solid {border_subtle};
}}
QWidget#DockCtrlPanel QLabel {{ background: transparent; color: {text_muted}; }}
QWidget#DockCtrlPanel QPushButton {{
    background: {bg_ctrl_btn}; border-color: {border_input}; padding: 3px 10px;
}}
QWidget#DockCtrlPanel QPushButton:hover {{ background: {interactive_ctrl_hover}; }}
QWidget#DockCtrlPanel QPushButton:pressed {{ background: {interactive_ctrl_pressed}; }}
QWidget#DockCtrlPanel QLineEdit, QWidget#DockCtrlPanel QSpinBox {{
    background: {bg_ctrl_input}; border-color: {border_input};
}}
QTableWidget {{ background: {bg_surface}; gridline-color: {bg_elevated}; alternate-background-color: {bg_raised}; }}
/* Dock title bar is a custom widget (DockTitleBar); style via object name */
QWidget#DockTitleBar {{
    background: {bg_dock_title};
    border-bottom: 1px solid {bg_surface};
}}
QLabel#DockTitle {{
    color: {dock_title_text};
    font-weight: bold;
    font-size: 11pt;
    background: transparent;
}}
QToolButton#DockCloseBtn, QToolButton#DockFloatBtn {{
    background: {dock_btn_bg};
    border: 1px solid {dock_btn_border};
    border-radius: 3px;
}}
QToolButton#DockCloseBtn:hover, QToolButton#DockFloatBtn:hover {{
    background: {dock_btn_hover_bg};
    border: 1px solid {dock_btn_hover_border};
}}
QToolButton#DockCloseBtn:pressed, QToolButton#DockFloatBtn:pressed {{
    background: {dock_btn_pressed_bg};
}}
QScrollBar:horizontal {{
    background: {bg_raised};
    height: 16px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {scroll_handle};
    min-width: 40px;
    border-radius: 6px;
    margin: 2px 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {scroll_handle_hover}; }}
QScrollBar::handle:horizontal:pressed {{ background: {scroll_handle_pressed}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0; height: 0; background: none; border: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: {bg_raised};
}}
QScrollBar:vertical {{
    background: {bg_raised};
    width: 16px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {scroll_handle};
    min-height: 40px;
    border-radius: 6px;
    margin: 2px 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {scroll_handle_hover}; }}
QScrollBar::handle:vertical:pressed {{ background: {scroll_handle_pressed}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    width: 0; height: 0; background: none; border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: {bg_raised};
}}
QScrollBar::corner {{ background: {bg_raised}; }}
QStatusBar {{ background: {bg_surface}; color: {text_status}; }}

/* Dock tab styling — make unselected tabs readable */
QTabBar::tab {{
    background: {bg_ctrl_panel};
    color: {text_secondary};
    padding: 6px 16px;
    border: 1px solid {border_subtle};
    border-bottom: none;
    margin-right: 2px;
    min-width: 90px;
}}
QTabBar::tab:selected {{
    background: {selection_bg};
    color: {tab_selected_text};
    font-weight: bold;
    border: 1px solid {interactive_ctrl_hover};
    border-bottom: 2px solid {accent_primary};
}}
QTabBar::tab:hover:!selected {{
    background: {tab_hover_bg};
    color: {tab_hover_text};
}}
QTreeWidget {{
    background: {bg_surface}; gridline-color: {bg_elevated};
    alternate-background-color: {bg_raised};
}}
QTreeWidget::item:selected {{ background: {selection_bg}; }}

/* QListView — used by QCompleter popups and other list widgets */
QListView {{
    background: {bg_raised};
    color: {text_primary};
    border: 1px solid {border_normal};
    outline: 0;
    selection-background-color: {selection_bg};
    selection-color: {text_white};
}}
QListView::item {{
    padding: 5px 10px;
    border: 0;
}}
QListView::item:selected {{
    background: {selection_bg};
    color: {text_white};
}}
QListView::item:hover {{
    background: {bg_elevated};
}}

/* QComboBox popup (dropdown arrow) — separate from QCompleter popup */
QComboBox QAbstractItemView {{
    background: {bg_raised};
    color: {text_primary};
    border: 1px solid {border_normal};
    outline: 0;
    selection-background-color: {selection_bg};
    selection-color: {text_white};
}}

/* Minimap strip separator is drawn in MinimapWidget.paintEvent — the
   stylesheet border-bottom doesn't apply to widgets with a custom
   paintEvent that fills their full rect. */

/* Menus — context menus and menubar dropdowns */
QMenu {{
    background: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border_normal};
    border-radius: 4px;
    padding: 6px 0;
}}
QMenu::item {{
    padding: 8px 36px 8px 20px;
    min-width: 200px;
    background: transparent;
}}
QMenu::item:selected {{
    background: {selection_bg};
    color: {text_white};
}}
QMenu::item:disabled {{
    color: {text_disabled};
}}
QMenu::indicator {{
    margin-left:15px;
    width: 12px;
    height: 12px;
}}
QMenu::right-arrow {{
    margin-right: 20px;
    width: 8px;
    height: 8px;
}}
QMenu::separator {{
    height: 1px;
    background: {border_normal};
    margin: 4px 8px;
}}

/* ── Dock resize handle (between docked panels and the central widget) ── */
QMainWindow::separator {{
    background: {border_normal};
    width: 4px;
    height: 4px;
}}
QMainWindow::separator:hover {{
    background: {accent_primary};
}}

/* ── Toolbar separator ──────────────────────────────────────── */
QToolBar::separator {{
    background: {interactive_ctrl_hover};
    width: 1px;
    margin: 4px 6px;
}}

/* ── Toolbar action buttons (Go / Next / Zoom to Selection) ─── */
QToolBar QToolButton {{
    background: {bg_ctrl_panel};
    color: {toolbar_btn_text};
    border: 1px solid {toolbar_btn_border};
    border-radius: 4px;
    padding: 3px 12px;
    min-width: 40px;
}}
QToolBar QToolButton:hover {{
    background: {toolbar_btn_hover_bg};
    border-color: {toolbar_btn_hover_border};
    color: {toolbar_btn_hover_text};
}}
QToolBar QToolButton:pressed {{
    background: {toolbar_btn_pressed_bg};
    border-color: {toolbar_btn_pressed_border};
    color: {text_white};
}}
QToolBar QToolButton:checked {{
    background: {accent_checked_bg};
    border: 1px solid {accent_checked_border};
    color: {accent_checked_text};
    font-weight: bold;
}}
QToolBar QToolButton:checked:hover {{
    background: {accent_checked_hover};
    border-color: {accent_checked_hover_border};
    color: {accent_checked_hover_text};
}}

/* ── Toolbar input fields ────────────────────────────────────── */
/* Brighter border so the fields are clearly legible against the toolbar. */
QToolBar QDoubleSpinBox, QToolBar QSpinBox, QToolBar QComboBox {{
    border-color: {border_input};
}}
QToolBar QDoubleSpinBox:focus, QToolBar QSpinBox:focus, QToolBar QComboBox:focus {{
    border-color: {accent_primary};
}}

/* ── Mode badge (status bar, right side) ─────────────────────── */
QLabel#ModeBadge {{
    background: {accent_checked_bg};
    color: {accent_checked_text};
    border: 1px solid {accent_checked_border};
    border-radius: 3px;
    padding: 1px 8px;
    font-weight: bold;
}}
"""


def build_dark_stylesheet() -> str:
    """Return the full application stylesheet with all theme tokens injected."""
    return _DARK_STYLESHEET_TMPL.format(
        sort_asc=(_ICONS / "sort_asc.svg").as_posix(),
        sort_desc=(_ICONS / "sort_desc.svg").as_posix(),
        **THEME,
    )


# Keep DARK_STYLESHEET as a backward-compatible alias (used by any code that
# may not have been updated yet — will be removed once all callers use
# build_dark_stylesheet()).
DARK_STYLESHEET = build_dark_stylesheet()

# Neutral alias — produces the correct stylesheet for whichever theme is active.
build_stylesheet = build_dark_stylesheet

# Flame-chart geometry
ROW_HEIGHT = 0.85           # data units (out of 1.0 row)
DEFAULT_WINDOW_US = 1000.0  # default visible time window in microseconds (= 1 ms)
