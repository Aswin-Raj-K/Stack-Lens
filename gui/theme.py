"""Design tokens — the single source of truth for all colors, spacing, fonts,
and z-order layers used across the CortexM0_Profiler GUI.

Themes are stored as JSON files in ``gui/themes/``.  Drop any ``*.json`` file
there and it will appear automatically in Settings → Appearance.  The display
name is derived from the filename: underscores become spaces and the result is
title-cased (e.g. ``my_theme.json`` → ``"My Theme"``).

Import from here instead of hardcoding hex values in individual widgets.
"""

import json
import pathlib

_ICONS      = pathlib.Path(__file__).parent / "icons"
_THEMES_DIR = pathlib.Path(__file__).parent / "themes"


def _load_themes(themes_dir: pathlib.Path) -> dict:
    """Scan *themes_dir* for ``*.json`` theme files and return a name→dict map.

    Files are loaded in sorted order (alphabetical by filename) so the built-in
    ``dark.json`` / ``light.json`` appear before any custom themes that start
    with later letters.  Malformed or unreadable files are silently skipped.
    """
    themes: dict = {}
    if not themes_dir.is_dir():
        return themes
    for path in sorted(themes_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            name = path.stem.replace("_", " ").title()
            themes[name] = data
        except Exception:
            pass
    return themes


# ── Theme registry ────────────────────────────────────────────────────
# Populated at import time from gui/themes/*.json.
THEMES: dict = _load_themes(_THEMES_DIR)

# Live mutable dict — all code reads THEME["key"] at call time so
# apply_theme() can swap contents in-place without rebinding imports.
_DEFAULT_NAME = "Dark" if "Dark" in THEMES else (next(iter(THEMES)) if THEMES else "")
THEME: dict = dict(THEMES.get(_DEFAULT_NAME, {}))
CURRENT_THEME_NAME: str = _DEFAULT_NAME

# ── RGBA tuples for QColor(r, g, b, a) calls in paintEvent ───────────
CANVAS_PAUSE_RGBA    = (110, 110, 120, 90)   # pause region fill
CANVAS_STICKY_RGBA   = (15,  15,  20,  220)  # sticky hover label bg
CANVAS_DIM_RGBA      = (0,   0,   0,   90)   # dim layer under highlight rect
PICK_A_FILL_ALPHA    = 110   # pick-span A semi-transparent fill
PICK_B_FILL_ALPHA    = 110   # pick-span B semi-transparent fill
SELECTION_FILL_ALPHA = 60    # drag-select overlay fill

# ── Spacing tokens (pixels) ──────────────────────────────────────────
SPACING = {
    "xs":  4,
    "sm":  6,
    "md":  10,
    "lg":  14,
    "xl":  20,
    "xxl": 28,
}

# ── Typography ───────────────────────────────────────────────────────
FONT_SANS = "Segoe UI, Arial, sans-serif"
FONT_MONO = "Consolas, 'Courier New', monospace"

# ── Z-order layers for pyqtgraph overlays ────────────────────────────
Z_SELECTION = 50    # drag-select region
Z_PICK      = 100   # pick span A/B overlay
Z_HIGHLIGHT = 200   # iteration pulse highlight rectangle


# ── Utility functions ────────────────────────────────────────────────

def apply_theme(name: str) -> None:
    """Switch the live THEME dict to the named palette.

    Updates THEME in-place so all existing THEME["key"] references
    immediately see new values without rebinding any imports.
    """
    global CURRENT_THEME_NAME
    if name not in THEMES:
        raise ValueError(f"Unknown theme {name!r}. Available: {list(THEMES)}")
    THEME.clear()
    THEME.update(THEMES[name])
    CURRENT_THEME_NAME = name


def spinbox_qss(prefix: str) -> str:
    """Return QSS for a QSpinBox or QDoubleSpinBox with chevron buttons.

    Args:
        prefix: ``"QSpinBox"`` or ``"QDoubleSpinBox"``
    """
    cu = (_ICONS / "chevron_up.svg").as_posix()
    cd = (_ICONS / "chevron_dn.svg").as_posix()
    T = THEME
    return (
        f"{prefix}::up-button {{"
        f"  subcontrol-origin: border; subcontrol-position: right top;"
        f"  width: 18px; background: {T['bg_raised']};"
        f"  border-left: 1px solid {T['border_normal']}; border-top-right-radius: 3px; }}"
        f"{prefix}::down-button {{"
        f"  subcontrol-origin: border; subcontrol-position: right bottom;"
        f"  width: 18px; background: {T['bg_raised']};"
        f"  border-left: 1px solid {T['border_normal']};"
        f"  border-top: 1px solid {T['border_normal']};"
        f"  border-bottom-right-radius: 3px; }}"
        f"{prefix}::up-button:hover, {prefix}::down-button:hover {{"
        f"  background: {T['interactive_hover_btn']}; }}"
        f"{prefix}::up-button:pressed, {prefix}::down-button:pressed {{"
        f"  background: {T['interactive_pressed_btn']}; }}"
        f"{prefix}::up-arrow {{ image: url({cu}); width: 7px; height: 5px; }}"
        f"{prefix}::down-arrow {{ image: url({cd}); width: 7px; height: 5px; }}"
    )


def primary_button_qss() -> str:
    """Return QSS for the primary action button (e.g. OK / Connect)."""
    T = THEME
    return (
        f"QPushButton {{"
        f"  background: {T['accent_pressed']}; border: 1px solid {T['accent_border']};"
        f"  color: {T['accent_text']}; border-radius: 3px; padding: 4px 16px; }}"
        f"QPushButton:hover {{"
        f"  background: {T['accent_hover']}; border-color: #5090c8; }}"
        f"QPushButton:pressed {{"
        f"  background: #142840; border-color: {T['accent_border']}; }}"
    )


def dialog_base_qss() -> str:
    """Return base QSS applied to every dialog — muted labels, themed borders."""
    T = THEME
    return (
        f"QLabel {{ color: {T['text_muted']}; }}"
        f"QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{"
        f"  border-color: {T['border_input']}; }}"
        f"QPushButton {{ border-color: {T['border_input']}; }}"
    )


def configure_pyqtgraph() -> None:
    """Apply current theme colors to pyqtgraph. Call once at app startup."""
    import pyqtgraph as pg
    pg.setConfigOptions(
        background=THEME["bg_base"],
        foreground=THEME["text_primary"],   # readable on both dark and light bg
    )
