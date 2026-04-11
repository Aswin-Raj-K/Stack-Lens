"""Main profiler window — flame chart, scrolling, menus, all features."""

import os
import pathlib
import sys

_RECENT_MAX = 8

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from trace_io import export_csv, export_json

from trace_io import import_json

from .call_tree_dock import CallTreeDock
from .color_bar import ColorBarWidget
from .constants import COLORS, DARK_STYLESHEET, DEFAULT_WINDOW_US, ROW_HEIGHT
from .dock_title_bar import DockTitleBar
from .flame_item import FlameItem
from .jitter_dialog import JitterDialog
from .marker_dock import MarkerDock
from .minimap_widget import MinimapWidget
from .ribbon_dock import RibbonDock
from .shortcut_overlay import ShortcutOverlay
from .summary_dock import SummaryDock
from .top_n_dock import TopNSlowestDock


# ── Custom axis that scales tick labels by a unit factor (us ↔ ms) ──

class UnitAxis(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit_scale = 1.0  # 1.0 = us, 0.001 = ms

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            scaled = v * self.unit_scale
            if abs(scaled) >= 1000:
                out.append(f"{scaled:.0f}")
            elif abs(scaled) >= 10:
                out.append(f"{scaled:.1f}")
            else:
                out.append(f"{scaled:.2f}")
        return out


class DepthAxis(pg.AxisItem):
    """Y-axis with integer depth labels centred vertically in each function bar.

    Bars occupy [depth, depth + ROW_HEIGHT] in data coords.
    Tick marks are placed at depth + ROW_HEIGHT/2 (bar centre).
    Only major ticks are returned — no minor subticks.
    """

    def tickValues(self, minVal, maxVal, size):
        half = ROW_HEIGHT / 2
        # With invertY(True) pyqtgraph passes minVal > maxVal, so normalise.
        lo_val = min(minVal, maxVal)
        hi_val = max(minVal, maxVal)
        lo = int(lo_val) - 1
        hi = int(hi_val) + 2
        major = [
            d + half
            for d in range(lo, hi + 1)
            if lo_val <= d + half <= hi_val
        ]
        return [(1, major)]  # one level → major only, no subticks

    def tickStrings(self, values, scale, spacing):
        half = ROW_HEIGHT / 2
        return [str(int(round(v - half))) for v in values]


# ── Helpers ──────────────────────────────────────────────────────────

class _ZoomKeyFilter(QtCore.QObject):
    """App-level filter for zoom-in/out via bare '+' and '-'.

    QShortcut key sequences are unreliable for shifted keys like '+' (reported
    as Key_Plus | ShiftModifier on most platforms). Checking event.text() is
    layout-independent and works regardless of which child widget has focus.
    """

    _INPUT_TYPES = (
        QtWidgets.QLineEdit,
        QtWidgets.QTextEdit,
        QtWidgets.QPlainTextEdit,
        QtWidgets.QComboBox,
    )

    def __init__(self, zoom_in, zoom_out, parent=None):
        super().__init__(parent)
        self._zoom_in = zoom_in
        self._zoom_out = zoom_out

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QtCore.QEvent.Type.KeyPress:
            text = event.text()
            focused = QtWidgets.QApplication.focusWidget()
            if not isinstance(focused, self._INPUT_TYPES):
                if text == "+":
                    self._zoom_in()
                    return True
                if text == "-":
                    self._zoom_out()
                    return True
        return False


class _QuestionKeyFilter(QtCore.QObject):
    """App-level event filter that triggers the shortcut overlay on '?'.

    Installed on QApplication so it fires before any widget's own
    keyPressEvent — including QTableWidget / QTreeWidget which would
    otherwise swallow the key for their own navigation.

    Skips the callback when the focused widget is an editable input
    (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox) so that typing
    '?' in a search box still works normally.
    """

    _INPUT_TYPES = (
        QtWidgets.QLineEdit,
        QtWidgets.QTextEdit,
        QtWidgets.QPlainTextEdit,
        QtWidgets.QComboBox,
    )

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            # Key_Question covers '?' on all layouts; Key_Slash + Shift
            # is the US-keyboard way to produce '?', caught as a fallback.
            is_question = key == QtCore.Qt.Key.Key_Question or (
                key == QtCore.Qt.Key.Key_Slash
                and event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
            )
            if is_question:
                focused = QtWidgets.QApplication.focusWidget()
                if not isinstance(focused, self._INPUT_TYPES):
                    self._callback()
                    return True  # consume — don't pass to the widget
        return False


# ── Main window ──────────────────────────────────────────────────────

class ProfilerWindow(QtWidgets.QMainWindow):
    """Flame-chart window with full navigation + filter + export + refresh."""

    def __init__(
        self,
        spans,
        marks=None,
        pause_regions=None,
        wrapped=False,
        refresh_fn=None,
        elf_path=None,
        cpu_mhz=96.0,
        parent=None,
    ):
        super().__init__(parent)
        self.spans = spans
        self.marks = list(marks or [])
        self.pause_regions = list(pause_regions or [])
        self.wrapped = bool(wrapped)
        self.refresh_fn = refresh_fn
        self.elf_path = elf_path
        self.cpu_mhz = cpu_mhz
        self._jlink = None  # live J-Link handle; closed on reconnect or window close

        self.setWindowTitle("Cortex-M Function Profiler")
        self.resize(1500, 900)

        # Data extents (always stored internally in microseconds)
        self._compute_extents()

        # Color map per function name — preserved across refreshes so colors stay stable
        self.color_map = {}
        self._update_color_map()

        # Display unit: "us" → 1.0, "ms" → 0.001. Default to ms.
        self.unit_label = "ms"
        self.unit_scale = 0.001

        # Current visible window
        self.window_us = min(DEFAULT_WINDOW_US, self.total_us) if self.total_us > 0 else 1.0
        self.view_start = 0.0

        # Span-picker state
        self._pick_mode = False
        self._picked_a = None
        self._picked_b = None
        self._pick_overlay_a = None
        self._pick_overlay_b = None

        # Zoom-to-selection state
        self._select_mode = False
        self._shift_drag_active = False  # Shift+drag mode-less region zoom
        self._select_start_x = None
        self._select_overlay = None

        # Iterator cursor for "jump to next occurrence" — tracks the last
        # function/marker the user clicked and the current index into its
        # occurrence list. Shared by summary dock, Find combobox, and marker
        # dock so any of them can advance the same cursor.
        self._iter_cursor = {"kind": None, "name": None, "index": 0}
        self._iter_highlight_item = None       # QGraphicsRectItem currently glowing
        self._iter_highlight_timer = None      # QTimer that removes it

        # Highlight-on-hover state (off by default)
        self.highlight_hover_enabled = False

        # Color mode
        self._color_mode = "function"

        self._build_ui()
        self._populate_plot()
        self._update_view_range()
        self._update_overflow_banner()

        # Make sure keyboard focus lands on the plot (not the toolbar's
        # Window spinbox) when the window first appears, so Home/End/F3 etc.
        # work without clicking on the chart first.
        self.plot_widget.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.plot_widget.setFocus()
        self._initial_focus_done = False

        # Keyboard pan/zoom shortcuts. Use QShortcut with WindowShortcut context
        # so they fire regardless of which child widget currently has focus
        # (the plot widget's QGraphicsView would otherwise swallow arrow keys,
        # and some child widgets consume +/- too).
        self._install_pan_zoom_shortcuts()

    def closeEvent(self, event):
        if self._jlink is not None:
            try:
                self._jlink.close()
            except Exception:
                pass
            self._jlink = None
        super().closeEvent(event)

    # ── Internal setup helpers ───────────────────────────────────────

    def _compute_extents(self):
        mins = []
        maxs = []
        if self.spans:
            mins.append(min(sp["start_us"] for sp in self.spans))
            maxs.append(max(sp["end_us"] for sp in self.spans))
        if self.marks:
            mins.append(min(m["t_us"] for m in self.marks))
            maxs.append(max(m["t_us"] for m in self.marks))

        if mins:
            self.t_min = min(mins)
            self.t_max = max(maxs)
        else:
            self.t_min, self.t_max = 0.0, 1.0

        if self.spans:
            self.max_depth = max(sp["depth"] for sp in self.spans)
        else:
            self.max_depth = 0

        # Display-y bounds: thread spans occupy 0..max_depth,
        # ISR spans occupy -1..-(isr_max_depth+1)
        isr_max = 0
        has_isr = False
        for sp in self.spans:
            if sp.get("ipsr", 0) != 0:
                has_isr = True
                if sp["depth"] > isr_max:
                    isr_max = sp["depth"]
        self.has_isr = has_isr
        self.isr_max_depth = isr_max
        # min_display_y: most-negative (top of chart under invertY)
        self.min_display_y = -(isr_max + 1) if has_isr else 0
        self.max_display_y = self.max_depth

        self.total_us = self.t_max - self.t_min
        self.func_names = sorted(set(sp["name"] for sp in self.spans))

    def _update_color_map(self):
        """Add stable colors for any new function names (keep existing)."""
        used = set(self.color_map.values())
        for i, name in enumerate(self.func_names):
            if name not in self.color_map:
                # Pick the first palette slot not already used
                for j in range(len(COLORS)):
                    candidate = COLORS[(i + j) % len(COLORS)]
                    if candidate not in used:
                        self.color_map[name] = candidate
                        used.add(candidate)
                        break
                else:
                    self.color_map[name] = COLORS[i % len(COLORS)]

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(DARK_STYLESHEET)

        # Create the shortcut cheat-sheet overlay + its trigger action
        # BEFORE _build_menu so the Help menu entry can reference it.
        #
        # Important: use a SINGLE QKeySequence for "?" — Qt canonicalises
        # both "?" and "Shift+/" to the same internal key, so passing
        # both to setShortcuts registers the same binding twice and Qt
        # then reports every press as an ambiguous overload and fires
        # nothing. One entry is enough to catch the key on every layout.
        self._shortcut_overlay = ShortcutOverlay(self)
        self._act_show_shortcuts = QtGui.QAction("Keyboard Shortcuts…", self)
        # No QAction shortcut — QTableWidget/QTreeWidget with focus intercept
        # key events before ApplicationShortcut fires. The app-level event
        # filter below is the reliable path. We keep the action for the Help
        # menu entry only.
        self._act_show_shortcuts.triggered.connect(self._shortcut_overlay.show_centered)
        self.addAction(self._act_show_shortcuts)

        # App-level event filter for '?' — fires before any widget's own
        # keyPressEvent, so it works regardless of focus owner.
        self._question_filter = _QuestionKeyFilter(
            self._shortcut_overlay.show_centered, self
        )
        QtWidgets.QApplication.instance().installEventFilter(self._question_filter)

        self._build_menu()
        self._build_toolbar()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)  # tight so minimap/plot are separated only by the 1px border

        # Overflow banner (hidden unless the ring buffer wrapped)
        self.overflow_banner = QtWidgets.QLabel()
        self.overflow_banner.setStyleSheet(
            "background:#6c1f1f; color:#ffeaea; padding:8px;"
            "border-radius:4px; font-weight:bold;"
        )
        self.overflow_banner.setVisible(False)
        layout.addWidget(self.overflow_banner)

        # Minimap strip — hidden by default (toggle via View → Show Minimap)
        self.minimap = MinimapWidget(
            self.spans, self.marks, self.color_map, self.t_min, self.total_us,
            pause_regions=self.pause_regions,
        )
        self.minimap.view_start_changed.connect(self._on_minimap_jump)
        self.minimap.setVisible(False)
        layout.addWidget(self.minimap)

        pg.setConfigOptions(
            antialias=False,
            background="#181820",
            foreground="#ffffff",
            useOpenGL=False,
        )

        self.x_axis = UnitAxis(orientation="bottom")
        self.x_axis.enableAutoSIPrefix(False)
        self.x_axis.unit_scale = self.unit_scale
        self.y_axis = DepthAxis(orientation="left")
        self.plot_widget = pg.PlotWidget(axisItems={"bottom": self.x_axis, "left": self.y_axis})
        self.plot = self.plot_widget.getPlotItem()
        self.plot.setLabel("bottom", f"Time ({self.unit_label})")
        self.plot.setLabel("left", "Call Depth")
        self.plot.showGrid(x=True, y=False, alpha=0.25)

        vb = self.plot.getViewBox()
        vb.invertY(True)
        vb.setMouseEnabled(x=False, y=False)
        vb.setMenuEnabled(False)
        vb.setDefaultPadding(0)

        # Override wheel event for horizontal scroll
        self.plot_widget.wheelEvent = self._plot_wheel_event

        # Save original mouse handlers so non-select-mode behavior falls through unchanged
        self._orig_mouse_press = self.plot_widget.mousePressEvent
        self._orig_mouse_move = self.plot_widget.mouseMoveEvent
        self._orig_mouse_release = self.plot_widget.mouseReleaseEvent
        self.plot_widget.mousePressEvent = self._plot_mouse_press
        self.plot_widget.mouseMoveEvent = self._plot_mouse_move
        self.plot_widget.mouseReleaseEvent = self._plot_mouse_release

        layout.addWidget(self.plot_widget, 1)

        # Measurement cursors (two draggable vertical lines)
        pen_a = pg.mkPen("#ff8800", width=2, style=QtCore.Qt.PenStyle.DashLine)
        pen_b = pg.mkPen("#00ddff", width=2, style=QtCore.Qt.PenStyle.DashLine)
        self.cursor_a = pg.InfiniteLine(
            pos=0, angle=90, movable=True, pen=pen_a,
            label="A", labelOpts={"position": 0.95, "color": "#ff8800"},
        )
        self.cursor_b = pg.InfiniteLine(
            pos=0, angle=90, movable=True, pen=pen_b,
            label="B", labelOpts={"position": 0.95, "color": "#00ddff"},
        )
        self.cursor_a.sigPositionChanged.connect(self._on_cursors_moved)
        self.cursor_b.sigPositionChanged.connect(self._on_cursors_moved)
        self.cursor_a.setVisible(False)
        self.cursor_b.setVisible(False)
        self.plot.addItem(self.cursor_a)
        self.plot.addItem(self.cursor_b)
        self.cursors_enabled = False

        # Scrollbar
        self.scrollbar = QtWidgets.QScrollBar(QtCore.Qt.Orientation.Horizontal)
        self.scrollbar.setSingleStep(1)
        self.scrollbar.valueChanged.connect(self._on_scroll)
        layout.addWidget(self.scrollbar)

        # Hover details bar
        self.hover_label = QtWidgets.QLabel("Hover over a bar to see details")
        self.hover_label.setStyleSheet(
            "background:#22222c; color:#ddd; padding:6px; border-radius:4px;"
        )
        layout.addWidget(self.hover_label)

        # Cursor measurement bar
        self.measure_label = QtWidgets.QLabel()
        self.measure_label.setStyleSheet(
            "background:#2a2a36; color:#fff; padding:6px; border-radius:4px; font-weight:bold;"
        )
        self.measure_label.setVisible(False)
        layout.addWidget(self.measure_label)

        # Pick-spans measurement bar (shows A→B delta when user picks two spans)
        self.pick_label = QtWidgets.QLabel()
        self.pick_label.setStyleSheet(
            "background:#2a2a36; color:#fff; padding:6px; border-radius:4px;"
        )
        self.pick_label.setVisible(False)
        layout.addWidget(self.pick_label)

        # Color-by-duration legend (hidden unless in duration mode)
        self.color_bar = ColorBarWidget()
        self.color_bar.setVisible(False)
        layout.addWidget(self.color_bar)

        # Status bar
        self._update_status_bar()

        # Summary dock (bottom)
        self.summary_dock = SummaryDock(self.spans, self.color_map, self)
        self.summary_dock.setTitleBarWidget(DockTitleBar(self.summary_dock))
        self.summary_dock.function_clicked.connect(self._jump_to_function_name)
        self.summary_dock.visibility_changed.connect(self._on_visibility_changed)
        self.summary_dock.analyze_jitter_requested.connect(self._show_jitter_for_function)
        self.summary_dock.ribbon_requested.connect(self._on_ribbon_requested)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.summary_dock)

        # Call-tree dock (bottom, tabbed with summary)
        self.call_tree_dock = CallTreeDock(self.spans, self.color_map, self.total_us, self)
        self.call_tree_dock.setTitleBarWidget(DockTitleBar(self.call_tree_dock))
        self.call_tree_dock.function_clicked.connect(self._jump_to_function_name)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.call_tree_dock)
        self.tabifyDockWidget(self.summary_dock, self.call_tree_dock)

        # Markers dock (bottom, tabbed with summary + call tree)
        self.marker_dock = MarkerDock(self.marks, self)
        self.marker_dock.setTitleBarWidget(DockTitleBar(self.marker_dock))
        self.marker_dock.mark_clicked.connect(self._jump_to_mark_name)
        self.marker_dock.visibility_changed.connect(self._on_mark_visibility_changed)
        self.marker_dock.analyze_jitter_requested.connect(self._show_jitter_for_marker)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.marker_dock)
        self.tabifyDockWidget(self.summary_dock, self.marker_dock)

        # Top-N slowest calls dock (bottom, tabbed)
        self.top_n_dock = TopNSlowestDock(self.spans, self.color_map, self)
        self.top_n_dock.setTitleBarWidget(DockTitleBar(self.top_n_dock))
        self.top_n_dock.span_clicked.connect(self._jump_to_span_instance)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.top_n_dock)
        self.tabifyDockWidget(self.summary_dock, self.top_n_dock)

        # Function Ribbon dock — starts empty; populated via Summary
        # context menu → "Show in Ribbon View"
        self.ribbon_dock = RibbonDock(
            self.spans, self.color_map, self.t_min, self.total_us, self,
        )
        self.ribbon_dock.setTitleBarWidget(DockTitleBar(self.ribbon_dock))
        self.ribbon_dock.tick_clicked.connect(self._on_ribbon_tick_clicked)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.ribbon_dock)
        self.tabifyDockWidget(self.summary_dock, self.ribbon_dock)

        self.summary_dock.raise_()

        self.resizeDocks([self.summary_dock], [260], QtCore.Qt.Orientation.Vertical)

        # Sync docks to the current display unit (default is ms)
        self.summary_dock.set_unit(self.unit_label, self.unit_scale)
        self.call_tree_dock.set_unit(self.unit_label, self.unit_scale)
        self.marker_dock.set_unit(self.unit_label, self.unit_scale)
        self.top_n_dock.set_unit(self.unit_label, self.unit_scale)

        # Now that the docks exist, populate the Panels submenu with their
        # toggle actions (they stay in sync with the dock's visibility state).
        self._populate_panels_menu()

        # Throttled hover
        self._hover_timer = QtCore.QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(20)
        self._hover_timer.timeout.connect(self._do_hover_update)
        self._last_mouse_pos = None
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_clicked)

    def _build_menu(self):
        menubar = self.menuBar()

        # ── File menu ──
        file_menu = menubar.addMenu("&File")

        act_open_trace = QtGui.QAction("Open Trace...", self)
        act_open_trace.setShortcut("Ctrl+O")
        act_open_trace.triggered.connect(self._open_trace_dialog)
        file_menu.addAction(act_open_trace)

        act_connect_jlink = QtGui.QAction("Connect to J-Link\u2026", self)
        act_connect_jlink.setShortcut("Ctrl+J")
        act_connect_jlink.triggered.connect(self._connect_jlink_dialog)
        file_menu.addAction(act_connect_jlink)

        # Recent traces submenu (populated from QSettings)
        self._recent_menu = file_menu.addMenu("Recent Traces")
        self._populate_recent_menu()

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("Export")
        act_export_json = QtGui.QAction("Export as JSON...", self)
        act_export_json.triggered.connect(self._export_json)
        export_menu.addAction(act_export_json)

        act_export_csv = QtGui.QAction("Export as CSV...", self)
        act_export_csv.triggered.connect(self._export_csv)
        export_menu.addAction(act_export_csv)

        file_menu.addSeparator()

        self.act_refresh = QtGui.QAction("Refresh Trace", self)
        self.act_refresh.setShortcut("F5")
        self.act_refresh.triggered.connect(self._refresh)
        self.act_refresh.setEnabled(self.refresh_fn is not None)
        file_menu.addAction(self.act_refresh)

        file_menu.addSeparator()

        act_quit = QtGui.QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # ── View menu ──
        view_menu = menubar.addMenu("&View")

        # Units submenu
        unit_menu = view_menu.addMenu("Units")
        self.unit_group = QtGui.QActionGroup(self)
        self.unit_group.setExclusive(True)
        act_us = QtGui.QAction("Microseconds (us)", self, checkable=True)
        act_us.setChecked(self.unit_label == "us")
        act_us.triggered.connect(lambda: self._set_unit("us"))
        self.unit_group.addAction(act_us)
        unit_menu.addAction(act_us)

        act_ms = QtGui.QAction("Milliseconds (ms)", self, checkable=True)
        act_ms.setChecked(self.unit_label == "ms")
        act_ms.triggered.connect(lambda: self._set_unit("ms"))
        self.unit_group.addAction(act_ms)
        unit_menu.addAction(act_ms)

        # Color-mode submenu
        color_menu = view_menu.addMenu("Color Mode")
        self.color_group = QtGui.QActionGroup(self)
        self.color_group.setExclusive(True)

        act_color_fn = QtGui.QAction("By Function", self, checkable=True)
        act_color_fn.setChecked(True)
        act_color_fn.triggered.connect(lambda: self._set_color_mode("function"))
        self.color_group.addAction(act_color_fn)
        color_menu.addAction(act_color_fn)

        act_color_dur = QtGui.QAction("By Duration (heat)", self, checkable=True)
        act_color_dur.triggered.connect(lambda: self._set_color_mode("duration"))
        self.color_group.addAction(act_color_dur)
        color_menu.addAction(act_color_dur)

        view_menu.addSeparator()

        # Minimap toggle (off by default)
        self.act_minimap = QtGui.QAction("Show Minimap", self, checkable=True)
        self.act_minimap.setChecked(False)
        self.act_minimap.setShortcut("Ctrl+Shift+M")
        self.act_minimap.triggered.connect(self._toggle_minimap)
        view_menu.addAction(self.act_minimap)

        # Dock panel toggles (Summary / Call Tree / Markers) — actions are
        # added in _populate_panels_menu() after the docks exist.
        self._panels_menu = view_menu.addMenu("Panels")

        view_menu.addSeparator()

        self.act_highlight = QtGui.QAction("Highlight Hovered Function", self, checkable=True)
        self.act_highlight.setChecked(False)
        self.act_highlight.setShortcut("Ctrl+H")
        self.act_highlight.triggered.connect(self._toggle_highlight)
        view_menu.addAction(self.act_highlight)

        self.act_bar_labels = QtGui.QAction("Show Function Names on Bars", self, checkable=True)
        self.act_bar_labels.setChecked(False)  # OFF by default
        self.act_bar_labels.setShortcut("Ctrl+L")
        self.act_bar_labels.triggered.connect(self._toggle_bar_labels)
        view_menu.addAction(self.act_bar_labels)

        self.act_sticky_hover = QtGui.QAction("Sticky Hover Label", self, checkable=True)
        self.act_sticky_hover.setChecked(False)  # OFF by default
        self.act_sticky_hover.triggered.connect(self._toggle_sticky_hover)
        view_menu.addAction(self.act_sticky_hover)

        self.act_cursors = QtGui.QAction("Measurement Cursors", self, checkable=True)
        self.act_cursors.setShortcut("Ctrl+M")
        self.act_cursors.triggered.connect(self._toggle_cursors)
        view_menu.addAction(self.act_cursors)

        self.act_pick_spans = QtGui.QAction("Pick Spans Mode", self, checkable=True)
        self.act_pick_spans.setShortcut("Ctrl+P")
        self.act_pick_spans.triggered.connect(self._toggle_pick_mode)
        view_menu.addAction(self.act_pick_spans)

        self.act_select_zoom = QtGui.QAction("Zoom to Selection", self, checkable=True)
        self.act_select_zoom.setShortcut("Ctrl+R")
        self.act_select_zoom.triggered.connect(self._toggle_select_zoom)
        view_menu.addAction(self.act_select_zoom)

        view_menu.addSeparator()

        act_reset = QtGui.QAction("Reset View", self)
        act_reset.setShortcut("Ctrl+0")
        act_reset.triggered.connect(self._reset_view)
        view_menu.addAction(act_reset)

        # ── Navigate menu ──
        nav_menu = menubar.addMenu("&Navigate")
        act_home = QtGui.QAction("Go to Start", self)
        act_home.setShortcut("Home")
        act_home.triggered.connect(lambda: self._set_view_start(0.0))
        nav_menu.addAction(act_home)

        act_end = QtGui.QAction("Go to End", self)
        act_end.setShortcut("End")
        act_end.triggered.connect(
            lambda: self._set_view_start(max(0.0, self.total_us - self.window_us))
        )
        nav_menu.addAction(act_end)

        nav_menu.addSeparator()

        # Iterate through occurrences of the most recently selected
        # function/marker (set via Find combobox, summary dock, or marker dock)
        act_next_occ = QtGui.QAction("Next Occurrence", self)
        act_next_occ.setShortcut("F3")
        act_next_occ.triggered.connect(self._iter_next)
        nav_menu.addAction(act_next_occ)

        act_prev_occ = QtGui.QAction("Previous Occurrence", self)
        act_prev_occ.setShortcut("Shift+F3")
        act_prev_occ.triggered.connect(self._iter_prev)
        nav_menu.addAction(act_prev_occ)

        # ── Help menu ──
        help_menu = menubar.addMenu("&Help")
        # Reuse the shortcut action created in __init__ (lives on self.*)
        # so the QAction's keyboard shortcut and menu entry are the same
        # instance, keeping the accelerator display consistent.
        help_menu.addAction(self._act_show_shortcuts)

    def _populate_panels_menu(self):
        """Add toggle actions for the three bottom docks.

        Uses QDockWidget.toggleViewAction() which is automatically wired to
        the dock's visibility state — clicking it hides/shows the dock and
        the checkmark stays in sync, even if the user closes the dock via
        its own title-bar X button.
        """
        summary_action = self.summary_dock.toggleViewAction()
        summary_action.setText("Function Summary")
        summary_action.setShortcut("Ctrl+Shift+F")
        self._panels_menu.addAction(summary_action)

        tree_action = self.call_tree_dock.toggleViewAction()
        tree_action.setText("Call Tree")
        tree_action.setShortcut("Ctrl+Shift+T")
        self._panels_menu.addAction(tree_action)

        marker_action = self.marker_dock.toggleViewAction()
        marker_action.setText("Markers")
        marker_action.setShortcut("Ctrl+Shift+K")
        self._panels_menu.addAction(marker_action)

        top_n_action = self.top_n_dock.toggleViewAction()
        top_n_action.setText("Top Slowest Calls")
        top_n_action.setShortcut("Ctrl+Shift+O")
        self._panels_menu.addAction(top_n_action)

    def _build_toolbar(self):
        tb = QtWidgets.QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.window_label = QtWidgets.QLabel(f" Window ({self.unit_label}): ")
        tb.addWidget(self.window_label)
        self.window_spin = QtWidgets.QDoubleSpinBox()
        self.window_spin.setRange(0.1, 1e12)
        self.window_spin.setDecimals(2 if self.unit_label == "us" else 4)
        self.window_spin.setValue(self.window_us * self.unit_scale)
        self.window_spin.setSingleStep(10.0 if self.unit_label == "us" else 0.01)
        self.window_spin.setMinimumWidth(140)
        self.window_spin.setKeyboardTracking(False)
        self.window_spin.valueChanged.connect(self._on_window_changed)
        tb.addWidget(self.window_spin)

        tb.addSeparator()

        self.jump_label = QtWidgets.QLabel(f" Jump to ({self.unit_label}): ")
        tb.addWidget(self.jump_label)
        self.jump_spin = QtWidgets.QDoubleSpinBox()
        self.jump_spin.setRange(0, 1e12)
        self.jump_spin.setDecimals(2 if self.unit_label == "us" else 4)
        self.jump_spin.setMinimumWidth(140)
        self.jump_spin.setKeyboardTracking(False)
        tb.addWidget(self.jump_spin)

        # Per-widget stylesheet for spinbox step buttons — needs absolute SVG
        # paths so it cannot live in the global DARK_STYLESHEET constant.
        _icons = pathlib.Path(__file__).parent / "icons"
        _cu = (_icons / "chevron_up.svg").as_posix()
        _cd = (_icons / "chevron_dn.svg").as_posix()
        _spinbox_qss = (
            "QDoubleSpinBox::up-button {"
            "  subcontrol-origin: border; subcontrol-position: right top;"
            "  width: 18px; background: #22222c;"
            "  border-left: 1px solid #3a3a4a; border-top-right-radius: 3px; }"
            "QDoubleSpinBox::down-button {"
            "  subcontrol-origin: border; subcontrol-position: right bottom;"
            "  width: 18px; background: #22222c;"
            "  border-left: 1px solid #3a3a4a; border-top: 1px solid #3a3a4a;"
            "  border-bottom-right-radius: 3px; }"
            "QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {"
            "  background: #2e2e3e; }"
            "QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed {"
            "  background: #1a1a26; }"
            f"QDoubleSpinBox::up-arrow {{ image: url({_cu}); width: 7px; height: 5px; }}"
            f"QDoubleSpinBox::down-arrow {{ image: url({_cd}); width: 7px; height: 5px; }}"
        )
        self.window_spin.setStyleSheet(_spinbox_qss)
        self.jump_spin.setStyleSheet(_spinbox_qss)

        jump_btn = QtGui.QAction("Go", self)
        jump_btn.triggered.connect(self._jump_to_time)
        tb.addAction(jump_btn)

        tb.addSeparator()

        tb.addWidget(QtWidgets.QLabel(" Find: "))
        self.search_combo = QtWidgets.QComboBox()
        self.search_combo.setEditable(True)
        self.search_combo.setMinimumWidth(260)
        self.search_combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        for name in self.func_names:
            self.search_combo.addItem(name)
        # Start with no selection — line edit shows the placeholder text
        self.search_combo.setCurrentIndex(-1)
        line_edit = self.search_combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("Find function...")
            line_edit.returnPressed.connect(self._on_search_return_pressed)
        self.search_combo.activated.connect(self._on_search_activated)
        tb.addWidget(self.search_combo)
        self.search_combo.setStyleSheet(
            # subcontrol-origin: border positions the drop-down at the widget's
            # right edge; Qt automatically constrains the inner QLineEdit to the
            # space left of the button — no extra padding-right needed.
            "QComboBox::drop-down {"
            "  subcontrol-origin: border; subcontrol-position: right center;"
            "  width: 18px; background: #22222c;"
            "  border-left: 1px solid #3a3a4a; border-radius: 0px 3px 3px 0px; }"
            "QComboBox::drop-down:hover { background: #2e2e3e; }"
            f"QComboBox::down-arrow {{ image: url({_cd}); width: 7px; height: 5px; }}"
        )

        # Search-as-you-type: QCompleter with substring match (not just prefix)
        self._search_completer = QtWidgets.QCompleter(self.func_names, self.search_combo)
        self._search_completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self._search_completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self._search_completer.setCompletionMode(
            QtWidgets.QCompleter.CompletionMode.PopupCompletion
        )
        self._search_completer.setMaxVisibleItems(12)
        self.search_combo.setCompleter(self._search_completer)

        # Completer popups are top-level windows; global QSS doesn't always
        # reach them. Style the popup directly so it matches the dark theme.
        _popup = self._search_completer.popup()
        if _popup is not None:
            _popup.setStyleSheet(
                "QListView {"
                "  background: #22222c;"
                "  color: #e0e0e0;"
                "  border: 1px solid #3a3a4a;"
                "  outline: 0;"
                "  padding: 2px;"
                "}"
                "QListView::item {"
                "  padding: 5px 10px;"
                "  min-height: 20px;"
                "}"
                "QListView::item:selected {"
                "  background: #3d3d52;"
                "  color: #ffffff;"
                "}"
                "QListView::item:hover {"
                "  background: #2a2a36;"
                "}"
            )

        # "Next" button — advances to the next occurrence of the currently
        # selected function (or the most recently jumped-to one).
        next_action = QtGui.QAction("Next", self)
        next_action.setToolTip("Jump to the next occurrence of the selected function (F3)")
        next_action.triggered.connect(self._iter_next)
        tb.addAction(next_action)

        tb.addSeparator()

        # Zoom to Selection (shares QAction with View menu)
        tb.addAction(self.act_select_zoom)

        if self.refresh_fn is not None:
            # Share the same QAction as the File menu entry (avoids duplicate F5 shortcut)
            tb.addAction(self.act_refresh)

    def _update_status_bar(self):
        self.statusBar().showMessage(
            f"{len(self.spans)} spans  |  "
            f"{len(self.func_names)} unique functions  |  "
            f"Total: {self.total_us * self.unit_scale:.2f} {self.unit_label}"
        )

    # ── Plot population ──────────────────────────────────────────────

    def _populate_plot(self):
        # Remove any previous flame item
        if hasattr(self, "_flame_item") and self._flame_item is not None:
            try:
                self.plot.removeItem(self._flame_item)
            except Exception:
                pass
        self._clear_picks()

        if not self.spans and not self.marks:
            return

        current_mode = "function"
        for act in self.color_group.actions() if hasattr(self, "color_group") else []:
            if act.isChecked():
                current_mode = "duration" if "Duration" in act.text() else "function"
                break

        self._flame_item = FlameItem(
            self.spans,
            self.color_map,
            self.t_min,
            color_mode=current_mode,
            marks=self.marks,
            pause_regions=self.pause_regions,
        )
        self._flame_item.set_hidden(
            self.summary_dock.hidden_names() if hasattr(self, "summary_dock") else set()
        )
        # Preserve current bar-labels toggle state across refresh/load
        if hasattr(self, "act_bar_labels") and self.act_bar_labels.isChecked():
            self._flame_item.set_show_bar_labels(True)
        if hasattr(self, "act_sticky_hover") and self.act_sticky_hover.isChecked():
            self._flame_item.set_show_sticky_hover(True)
        self.plot.addItem(self._flame_item)

        y_top = self.min_display_y - 0.2
        y_bot = self.max_display_y + 1.0
        self.plot.setYRange(y_top, y_bot, padding=0)

        vb = self.plot.getViewBox()
        vb.setLimits(
            xMin=0,
            xMax=max(self.total_us, 1.0),
            yMin=y_top - 0.3,
            yMax=y_bot + 0.5,
        )

    # ── Live refresh ─────────────────────────────────────────────────

    def _refresh(self):
        if self.refresh_fn is None:
            return
        try:
            result = self.refresh_fn()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Refresh failed", str(e))
            return

        # refresh_fn returns (spans, marks, pause_regions, wrapped)
        if isinstance(result, tuple) and len(result) == 4:
            new_spans, new_marks, new_pauses, new_wrapped = result
        elif isinstance(result, tuple) and len(result) == 3:
            new_spans, new_marks, new_wrapped = result
            new_pauses = []
        else:
            new_spans, new_marks, new_pauses, new_wrapped = result, [], [], False

        if not new_spans and not new_marks:
            self.statusBar().showMessage("Refresh: no trace events yet", 3000)
            return

        self._apply_new_data(new_spans, new_marks, new_pauses, new_wrapped, preserve_view=True)

    # ── Export ───────────────────────────────────────────────────────

    def _export_json(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export to JSON", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            export_json(
                path,
                self.spans,
                meta={
                    "cpu_mhz": self.cpu_mhz,
                    "elf_path": self.elf_path or "",
                    "total_us": self.total_us,
                },
                marks=self.marks,
                pause_regions=self.pause_regions,
                wrapped=self.wrapped,
            )
            self.statusBar().showMessage(
                f"Exported {len(self.spans)} spans, {len(self.marks)} marks, "
                f"{len(self.pause_regions)} pause regions to {path}",
                4000,
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Export failed", str(e))

    def _export_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export to CSV", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            export_csv(path, self.spans)
            self.statusBar().showMessage(f"Exported {len(self.spans)} spans to {path}", 4000)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Export failed", str(e))

    # ── Open Trace / Recent ─────────────────────────────────────────

    def _connect_jlink_dialog(self):
        """File → Connect to J-Link... — establish a live J-Link session from the GUI."""
        from trace_reader import TRACE_BUFFER_SIZE, connect_jlink, load_elf_symbols, read_trace
        from span_builder import build_spans, parse_events, resolve_names
        from .jlink_connect_dialog import ConnectJLinkDialog

        dlg = ConnectJLinkDialog(
            elf_path=self.elf_path or "",
            cpu_mhz=self.cpu_mhz,
            parent=self,
        )
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        elf_path, device, cpu_mhz = dlg.get_params()
        if not elf_path:
            QtWidgets.QMessageBox.warning(self, "Connect failed", "Please select an ELF file.")
            return

        # Close any previous J-Link connection
        if self._jlink is not None:
            try:
                self._jlink.close()
            except Exception:
                pass
            self._jlink = None

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            name_to_addr, addr_to_name = load_elf_symbols(elf_path)
            jlink = connect_jlink(device)

            def read_and_parse():
                raw_buf, trace_idx = read_trace(jlink, name_to_addr)
                n_events = min(trace_idx, TRACE_BUFFER_SIZE)
                wrapped = trace_idx > TRACE_BUFFER_SIZE
                if n_events == 0:
                    return [], [], [], wrapped
                events = parse_events(raw_buf, trace_idx)
                resolve_names(events, addr_to_name, elf_path=elf_path)
                spans, marks, pause_regions = build_spans(events, cpu_mhz)
                return spans, marks, pause_regions, wrapped

            spans, marks, pause_regions, wrapped = read_and_parse()
        except Exception as exc:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Connect failed", str(exc))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self._jlink = jlink
        self.refresh_fn = read_and_parse
        self.elf_path = elf_path
        self.cpu_mhz = cpu_mhz
        self.act_refresh.setEnabled(True)

        if not spans and not marks:
            self.statusBar().showMessage(
                "Connected \u2014 no trace events yet. Press F5 to refresh.", 5000
            )
            return

        self._apply_new_data(spans, marks, pause_regions, wrapped, preserve_view=False)
        self.statusBar().showMessage(
            f"Connected to {device}: {len(spans)} spans, {len(marks)} marks", 5000
        )

    def _open_trace_dialog(self):
        """File → Open Trace... — load a JSON previously exported by this tool."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Trace", "", "Trace JSON (*.json);;All Files (*)"
        )
        if not path:
            return
        self._open_trace(path)

    def _open_trace(self, path):
        """Load a JSON trace file and install it as the current data."""
        try:
            spans, marks, pause_regions, meta = import_json(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Open Trace failed", f"Could not read {path}:\n{e}"
            )
            return

        if not spans and not marks:
            QtWidgets.QMessageBox.information(
                self, "Empty trace", f"{path} contains no spans or marks."
            )
            return

        self._apply_new_data(
            spans,
            list(marks),
            list(pause_regions),
            bool(meta.get("wrapped", False)),
            preserve_view=False,
        )

        # Persist + refresh the Recent menu
        self._add_recent_trace(path)

        self.statusBar().showMessage(
            f"Loaded {len(spans)} spans, {len(marks)} marks, "
            f"{len(pause_regions)} pause regions from {os.path.basename(path)}",
            5000,
        )
        QtCore.QTimer.singleShot(5100, self._update_status_bar)

    def _populate_recent_menu(self):
        """Rebuild the Recent Traces submenu from QSettings."""
        self._recent_menu.clear()
        settings = QtCore.QSettings("IxanaProfiler", "Profiler")
        recent = settings.value("recent_traces", []) or []
        # QSettings on some platforms stores a single string instead of a list
        if isinstance(recent, str):
            recent = [recent]

        if not recent:
            empty = QtGui.QAction("(empty)", self)
            empty.setEnabled(False)
            self._recent_menu.addAction(empty)
            return

        for path in recent:
            name = os.path.basename(path)
            act = QtGui.QAction(name, self)
            act.setToolTip(path)
            # capture p in the default arg so the lambda doesn't close over the loop var
            act.triggered.connect(lambda checked=False, p=path: self._open_trace(p))
            self._recent_menu.addAction(act)

        self._recent_menu.addSeparator()
        clear = QtGui.QAction("Clear", self)
        clear.triggered.connect(self._clear_recent_traces)
        self._recent_menu.addAction(clear)

    def _add_recent_trace(self, path):
        settings = QtCore.QSettings("IxanaProfiler", "Profiler")
        recent = settings.value("recent_traces", []) or []
        if isinstance(recent, str):
            recent = [recent]
        # Move to front, dedupe, cap
        recent = [p for p in recent if p != path]
        recent.insert(0, path)
        recent = recent[:_RECENT_MAX]
        settings.setValue("recent_traces", recent)
        self._populate_recent_menu()

    def _clear_recent_traces(self):
        settings = QtCore.QSettings("IxanaProfiler", "Profiler")
        settings.setValue("recent_traces", [])
        self._populate_recent_menu()

    def _apply_new_data(self, spans, marks, pause_regions, wrapped, *, preserve_view=True):
        """Swap in a fresh (spans, marks, pauses) tuple.

        Shared by `_refresh()` (live J-Link reads) and `_open_trace()` (JSON
        load). When `preserve_view=True` the current scroll position and
        window size are retained if they still fit the new data; otherwise
        the view is reset to the default 1 ms window at t=0.
        """
        if preserve_view:
            preserved_start = self.view_start
            preserved_window = self.window_us

        self.spans = spans
        self.marks = list(marks or [])
        self.pause_regions = list(pause_regions or [])
        self.wrapped = bool(wrapped)
        self._compute_extents()
        self._update_color_map()

        # Reset iterator cursor and any leftover highlight
        self._iter_cursor = {"kind": None, "name": None, "index": 0}
        self._clear_iter_highlight()

        # Rebuild Find combobox + completer
        self.search_combo.blockSignals(True)
        self.search_combo.clear()
        for name in self.func_names:
            self.search_combo.addItem(name)
        self.search_combo.setCurrentIndex(-1)
        self.search_combo.blockSignals(False)
        self._update_search_completer()

        # Rebuild docks
        self.summary_dock.set_spans(self.spans, self.color_map)
        self.call_tree_dock.set_spans(self.spans, self.total_us, self.color_map)
        self.marker_dock.set_marks(self.marks)
        self.marker_dock.set_unit(self.unit_label, self.unit_scale)
        self.top_n_dock.set_spans(self.spans, self.color_map)
        self.top_n_dock.set_unit(self.unit_label, self.unit_scale)
        if hasattr(self, "ribbon_dock") and self.ribbon_dock is not None:
            self.ribbon_dock.set_data(
                self.spans, self.color_map, self.t_min, self.total_us,
            )

        # Rebuild plot + minimap
        self._populate_plot()
        self.minimap.set_data(
            self.spans, self.marks, self.color_map, self.t_min, self.total_us,
            pause_regions=self.pause_regions,
        )
        self._update_overflow_banner()

        # Restore or reset view
        if preserve_view:
            self.view_start = min(
                preserved_start, max(0.0, self.total_us - preserved_window)
            )
            self.window_us = min(preserved_window, max(0.1, self.total_us))
        else:
            self.view_start = 0.0
            self.window_us = (
                min(DEFAULT_WINDOW_US, self.total_us) if self.total_us > 0 else 1.0
            )

        self.window_spin.blockSignals(True)
        self.window_spin.setValue(self.window_us * self.unit_scale)
        self.window_spin.blockSignals(False)

        self._update_view_range()
        self._update_status_bar()

    # ── Unit switching ───────────────────────────────────────────────

    def _set_unit(self, unit):
        self.unit_label = unit
        self.unit_scale = 1.0 if unit == "us" else 0.001

        self.x_axis.unit_scale = self.unit_scale
        self.plot.setLabel("bottom", f"Time ({unit})")
        self.x_axis.update()

        self.window_label.setText(f" Window ({unit}): ")
        self.jump_label.setText(f" Jump to ({unit}): ")

        self.window_spin.blockSignals(True)
        self.window_spin.setValue(self.window_us * self.unit_scale)
        self.window_spin.setSingleStep(10.0 if unit == "us" else 0.01)
        self.window_spin.blockSignals(False)

        self.jump_spin.blockSignals(True)
        self.jump_spin.setValue(self.view_start * self.unit_scale)
        self.jump_spin.blockSignals(False)

        # Update docks so their headers + numeric columns reflect the new unit
        if hasattr(self, "summary_dock") and self.summary_dock is not None:
            self.summary_dock.set_unit(unit, self.unit_scale)
        if hasattr(self, "call_tree_dock") and self.call_tree_dock is not None:
            self.call_tree_dock.set_unit(unit, self.unit_scale)
        if hasattr(self, "marker_dock") and self.marker_dock is not None:
            self.marker_dock.set_unit(unit, self.unit_scale)
        if hasattr(self, "top_n_dock") and self.top_n_dock is not None:
            self.top_n_dock.set_unit(unit, self.unit_scale)

        self._update_status_bar()
        self._update_measure_label()
        self._update_pick_label()
        self._refresh_hover_label()
        self._update_color_bar()

    # ── Color mode ───────────────────────────────────────────────────

    def _set_color_mode(self, mode):
        self._color_mode = mode
        if hasattr(self, "_flame_item") and self._flame_item is not None:
            self._flame_item.set_color_mode(mode)
            self._update_color_bar()
        self._update_status_bar()

    def _update_color_bar(self):
        """Show/hide the viridis legend based on color mode."""
        if self._color_mode == "duration" and hasattr(self, "_flame_item"):
            self.color_bar.set_range(
                self._flame_item.duration_min_us,
                self._flame_item.duration_max_us,
                self.unit_label,
                self.unit_scale,
            )
            self.color_bar.setVisible(True)
        else:
            self.color_bar.setVisible(False)

    # ── Highlight-on-hover toggle ────────────────────────────────────

    def _toggle_highlight(self, checked):
        self.highlight_hover_enabled = checked
        if not checked and hasattr(self, "_flame_item") and self._flame_item is not None:
            self._flame_item.set_highlighted_name(None)

    def _toggle_bar_labels(self, checked):
        """View > Show Function Names on Bars."""
        if hasattr(self, "_flame_item") and self._flame_item is not None:
            self._flame_item.set_show_bar_labels(checked)

    def _toggle_sticky_hover(self, checked):
        """View > Sticky Hover Label."""
        if hasattr(self, "_flame_item") and self._flame_item is not None:
            self._flame_item.set_show_sticky_hover(checked)
            if checked:
                # Seed with whatever the hover is currently pointing at
                self._refresh_sticky_hover_text()
            else:
                self._flame_item.set_sticky_text("")

    # ── Visibility filter ────────────────────────────────────────────

    def _on_visibility_changed(self, hidden_set):
        if hasattr(self, "_flame_item") and self._flame_item is not None:
            self._flame_item.set_hidden(hidden_set)

    # ── Toolbar handlers ─────────────────────────────────────────────

    def _on_window_changed(self, value):
        self.window_us = value / self.unit_scale
        self._update_view_range()

    def _jump_to_time(self):
        self.view_start = max(0, self.jump_spin.value() / self.unit_scale)
        self._update_view_range()

    # ── View range / scrollbar sync ─────────────────────────────────

    def _update_view_range(self):
        if self.window_us >= self.total_us:
            self.view_start = 0.0
            end = self.window_us
        else:
            end = self.view_start + self.window_us
            if end > self.total_us:
                end = self.total_us
                self.view_start = max(0.0, end - self.window_us)

        self.plot.setXRange(self.view_start, end, padding=0)

        scrollable = max(0.0, self.total_us - self.window_us)
        max_scroll = int(scrollable * 10)
        self.scrollbar.blockSignals(True)
        self.scrollbar.setRange(0, max_scroll)
        self.scrollbar.setPageStep(max(1, int(self.window_us * 10)))
        self.scrollbar.setValue(int(self.view_start * 10))
        self.scrollbar.setEnabled(max_scroll > 0)
        self.scrollbar.blockSignals(False)

        # Sync minimap viewport overlay
        if hasattr(self, "minimap"):
            self.minimap.set_viewport(
                self.t_min + self.view_start,
                self.t_min + end,
            )
        if hasattr(self, "ribbon_dock") and self.ribbon_dock is not None:
            self.ribbon_dock.set_viewport(
                self.t_min + self.view_start,
                self.t_min + end,
            )

    def _on_scroll(self, value):
        self.view_start = value / 10.0
        self.plot.setXRange(self.view_start, self.view_start + self.window_us, padding=0)
        if hasattr(self, "minimap"):
            self.minimap.set_viewport(
                self.t_min + self.view_start,
                self.t_min + self.view_start + self.window_us,
            )
        if hasattr(self, "ribbon_dock") and self.ribbon_dock is not None:
            self.ribbon_dock.set_viewport(
                self.t_min + self.view_start,
                self.t_min + self.view_start + self.window_us,
            )

    def _on_minimap_jump(self, start_us_abs):
        """Minimap widget asked us to jump — start_us_abs is absolute us."""
        self.view_start = max(0.0, start_us_abs - self.t_min)
        self._update_view_range()

    def _toggle_minimap(self, checked):
        self.minimap.setVisible(checked)

    def _update_overflow_banner(self):
        if self.wrapped:
            shown = len(self.spans)
            tail = f" and {len(self.marks)} marks." if self.marks else "."
            self.overflow_banner.setText(
                f"WARNING: Trace buffer wrapped - oldest events lost. "
                f"Showing the most recent {shown} reconstructed spans" + tail
            )
            self.overflow_banner.setVisible(True)
        else:
            self.overflow_banner.setVisible(False)

    def _set_view_start(self, start_us):
        self.view_start = max(0, min(start_us, max(0, self.total_us - self.window_us)))
        self._update_view_range()

    # ── Wheel → horizontal pan ───────────────────────────────────────

    def _plot_wheel_event(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            return
        mods = event.modifiers()
        if mods & QtCore.Qt.KeyboardModifier.ControlModifier:
            # Ctrl+scroll → zoom anchored to the mouse cursor position
            pos = event.position()
            scene_pos = self.plot_widget.mapToScene(
                QtCore.QPoint(int(pos.x()), int(pos.y()))
            )
            anchor_us = self.plot.vb.mapSceneToView(scene_pos).x()
            anchor_us = max(self.view_start,
                            min(anchor_us, self.view_start + self.window_us))
            anchor_frac = (
                (anchor_us - self.view_start) / self.window_us
                if self.window_us > 0 else 0.5
            )
            factor = 0.8 if delta > 0 else 1.25
            new_window = max(0.1, min(self.window_us * factor, self.total_us))
            new_start = anchor_us - anchor_frac * new_window
            self.view_start = max(0.0, min(new_start,
                                           max(0.0, self.total_us - new_window)))
            self.window_us = new_window
            self.window_spin.blockSignals(True)
            self.window_spin.setValue(self.window_us * self.unit_scale)
            self.window_spin.blockSignals(False)
            self._update_view_range()
        else:
            fraction = 0.5 if (mods & QtCore.Qt.KeyboardModifier.ShiftModifier) else 0.1
            pan_us = self.window_us * fraction * (-1 if delta > 0 else 1)
            self.view_start = max(
                0.0,
                min(self.view_start + pan_us, max(0.0, self.total_us - self.window_us)),
            )
            self._update_view_range()
        event.accept()

    # ── Measurement cursors ─────────────────────────────────────────

    def _toggle_cursors(self, checked):
        self.cursors_enabled = checked
        if checked:
            a = self.view_start + self.window_us * 0.25
            b = self.view_start + self.window_us * 0.75
            self.cursor_a.setPos(a)
            self.cursor_b.setPos(b)
        self.cursor_a.setVisible(checked)
        self.cursor_b.setVisible(checked)
        self.measure_label.setVisible(checked)
        if checked:
            self._update_measure_label()

    def _on_cursors_moved(self):
        if self.cursors_enabled:
            self._update_measure_label()

    def _update_measure_label(self):
        if not self.cursors_enabled:
            return
        a = self.cursor_a.value()
        b = self.cursor_b.value()
        delta = abs(b - a)
        u = self.unit_label
        s = self.unit_scale
        if delta > 0:
            self.measure_label.setText(
                f"A: {a * s:.3f} {u}    "
                f"B: {b * s:.3f} {u}    "
                f"Delta: {delta * s:.3f} {u}    "
                f"({1_000_000 / delta:.1f} Hz)"
            )
        else:
            self.measure_label.setText(
                f"A: {a * s:.3f} {u}    B: {b * s:.3f} {u}    Delta: 0"
            )

    # ── Pick-spans: click two bars, measure between them ───────────

    def _toggle_pick_mode(self, checked):
        self._pick_mode = checked
        self._clear_picks()
        self.pick_label.setVisible(checked)
        if checked:
            self.pick_label.setText("Pick span A (click a bar)")

    # ── Zoom to Selection (drag-to-zoom) ─────────────────────────────

    def _toggle_select_zoom(self, checked):
        self._select_mode = checked
        if checked:
            self.plot_widget.setCursor(QtCore.Qt.CursorShape.CrossCursor)
            self.statusBar().showMessage(
                "Drag horizontally on the chart, release to zoom. Esc to cancel."
            )
        else:
            self.plot_widget.unsetCursor()
            self._cancel_select_overlay()
            self._update_status_bar()

    def _plot_mouse_press(self, event):
        # Shift + Left-drag: mode-less region zoom (alternative to the
        # toolbar Select Zoom action). Uses the same overlay + release
        # machinery but doesn't require entering a mode.
        is_shift_drag = (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            and not self._select_mode
        )
        if self._select_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
            vp = self._view_x_from_event(event)
            self._select_start_x = vp
            self._select_overlay = pg.LinearRegionItem(
                values=[vp, vp],
                movable=False,
                brush=(255, 200, 0, 60),
                pen=pg.mkPen("#ffcc00", width=1),
            )
            self._select_overlay.setZValue(50)
            self.plot.addItem(self._select_overlay)
            event.accept()
            return
        if is_shift_drag:
            vp = self._view_x_from_event(event)
            self._select_start_x = vp
            self._shift_drag_active = True
            self._select_overlay = pg.LinearRegionItem(
                values=[vp, vp],
                movable=False,
                brush=(255, 200, 0, 60),
                pen=pg.mkPen("#ffcc00", width=1),
            )
            self._select_overlay.setZValue(50)
            self.plot.addItem(self._select_overlay)
            self.plot_widget.setCursor(QtCore.Qt.CursorShape.CrossCursor)
            event.accept()
            return
        self._orig_mouse_press(event)

    def _plot_mouse_move(self, event):
        if (self._select_mode or getattr(self, "_shift_drag_active", False)) and self._select_start_x is not None:
            vp = self._view_x_from_event(event)
            self._select_overlay.setRegion([self._select_start_x, vp])
            event.accept()
            return
        self._orig_mouse_move(event)

    def _plot_mouse_release(self, event):
        if (
            (self._select_mode or getattr(self, "_shift_drag_active", False))
            and self._select_start_x is not None
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            vp = self._view_x_from_event(event)
            x1 = max(0.0, min(self._select_start_x, vp))
            x2 = min(self.total_us, max(self._select_start_x, vp))
            width = x2 - x1
            was_shift_drag = getattr(self, "_shift_drag_active", False)
            self._cancel_select_overlay()

            # Only apply if the selection is meaningful (avoid accidental zero-width clicks)
            min_width = max(1e-3, 1e-6 * self.total_us)
            if width >= min_width:
                self.view_start = x1
                self.window_us = width
                self.window_spin.blockSignals(True)
                self.window_spin.setValue(width * self.unit_scale)
                self.window_spin.blockSignals(False)
                self._update_view_range()

            if was_shift_drag:
                self._shift_drag_active = False
                self.plot_widget.unsetCursor()
            else:
                # Auto-exit toolbar select mode (one-shot)
                self.act_select_zoom.setChecked(False)
                self._toggle_select_zoom(False)
            event.accept()
            return
        self._orig_mouse_release(event)

    def _view_x_from_event(self, event):
        """Map a QMouseEvent position to data-coordinate X (absolute microseconds)."""
        vb = self.plot.getViewBox()
        # event.pos() is in widget coords; map to scene then view
        try:
            scene_pt = self.plot_widget.mapToScene(event.position().toPoint())
        except AttributeError:
            # Older PySide6 compat
            scene_pt = self.plot_widget.mapToScene(event.pos())
        return vb.mapSceneToView(scene_pt).x()

    def _cancel_select_overlay(self):
        if self._select_overlay is not None:
            try:
                self.plot.removeItem(self._select_overlay)
            except Exception:
                pass
            self._select_overlay = None
        self._select_start_x = None

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            if getattr(self, "_shortcut_overlay", None) is not None and self._shortcut_overlay.isVisible():
                self._shortcut_overlay.hide()
                event.accept()
                return
            if self._select_mode:
                self.act_select_zoom.setChecked(False)
                self._toggle_select_zoom(False)
                event.accept()
                return
            # Esc also clears any persistent flame-chart highlight (e.g.
            # set by the hover-highlight toggle).
            if hasattr(self, "_flame_item") and self._flame_item is not None:
                self._flame_item.set_highlighted_name(None)
        super().keyPressEvent(event)

    def _install_pan_zoom_shortcuts(self):
        """Register keyboard pan/zoom as QShortcuts so they fire from anywhere
        in the window (not blocked by the plot widget's QGraphicsView)."""
        ctx = QtCore.Qt.ShortcutContext.WindowShortcut

        def sc(keys, handler):
            """Register one shortcut (or alternate set of keys) to `handler`."""
            for key in keys if isinstance(keys, (list, tuple)) else [keys]:
                s = QtGui.QShortcut(QtGui.QKeySequence(key), self)
                s.setContext(ctx)
                s.activated.connect(handler)

        # Pan left / right — 10%
        sc("Left",        lambda: self._pan_by_fraction(-0.1))
        sc("Right",       lambda: self._pan_by_fraction(0.1))
        # Fast pan — 50%
        sc("Shift+Left",  lambda: self._pan_by_fraction(-0.5))
        sc("Shift+Right", lambda: self._pan_by_fraction(0.5))
        # Fine pan — 1%
        sc("[",           lambda: self._pan_by_fraction(-0.01))
        sc("]",           lambda: self._pan_by_fraction(0.01))

        # Zoom in/out via '+' and '-': handled by an app-level text filter so
        # they work regardless of focus and keyboard layout (QShortcut is
        # unreliable for shifted keys like '+').
        self._zoom_filter = _ZoomKeyFilter(
            zoom_in=lambda: self._scale_window(0.5),
            zoom_out=lambda: self._scale_window(2.0),
            parent=self,
        )
        QtWidgets.QApplication.instance().installEventFilter(self._zoom_filter)

    def _pan_by_fraction(self, frac):
        """Shift view_start by `frac * window_us`. Negative = left, positive = right."""
        if self.total_us <= 0:
            return
        new_start = self.view_start + self.window_us * frac
        max_start = max(0.0, self.total_us - self.window_us)
        self.view_start = max(0.0, min(new_start, max_start))
        self._update_view_range()

    def _scale_window(self, factor):
        """Multiply window_us by `factor` (0.5 = zoom in, 2.0 = zoom out),
        keeping the current view center fixed."""
        if self.total_us <= 0:
            return
        center = self.view_start + self.window_us / 2
        new_window = max(0.1, min(self.window_us * factor, self.total_us))
        self.window_us = new_window
        self.view_start = max(0.0, min(center - new_window / 2,
                                       max(0.0, self.total_us - new_window)))
        self.window_spin.blockSignals(True)
        self.window_spin.setValue(self.window_us * self.unit_scale)
        self.window_spin.blockSignals(False)
        self._update_view_range()

    def showEvent(self, event):
        """Override to re-grab keyboard focus on the very first show.

        Some desktops reset focus during Qt's first showEvent pass; deferring
        the setFocus call to the next event-loop iteration via a 0-ms timer
        is the standard idiom for "override Qt's initial focus".
        """
        super().showEvent(event)
        if not getattr(self, "_initial_focus_done", False):
            self._initial_focus_done = True
            QtCore.QTimer.singleShot(0, self.plot_widget.setFocus)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the shortcut overlay matched to the full window area so it
        # can re-centre its panel on the new geometry.
        if getattr(self, "_shortcut_overlay", None) is not None:
            self._shortcut_overlay.setGeometry(self.rect())

    def _on_plot_clicked(self, ev):
        if not self._pick_mode:
            return
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        vb = self.plot.getViewBox()
        pt = vb.mapSceneToView(ev.scenePos())
        x_rel = pt.x()
        y = pt.y()
        depth = int(y)
        hit = self._find_span_at(depth, x_rel, y)
        if not hit:
            return

        if self._picked_a is None or self._picked_b is not None:
            # Start a fresh pair
            self._clear_picks()
            self._picked_a = hit
            self._pick_overlay_a = self._draw_pick_overlay(hit, "a")
        else:
            self._picked_b = hit
            self._pick_overlay_b = self._draw_pick_overlay(hit, "b")

        self._update_pick_label()

    def _draw_pick_overlay(self, sp, which):
        """Add a translucent highlight rectangle over the picked span."""
        border = QtGui.QColor("#ff8800") if which == "a" else QtGui.QColor("#00ddff")
        fill = QtGui.QColor(border)
        fill.setAlpha(110)

        x0 = sp["start_us"] - self.t_min
        w = max(sp["duration_us"], 0.1)

        rect = QtWidgets.QGraphicsRectItem(x0, sp["depth"], w, ROW_HEIGHT)
        rect.setBrush(QtGui.QBrush(fill))
        pen = QtGui.QPen(border)
        pen.setWidthF(0)
        rect.setPen(pen)
        rect.setZValue(100)
        self.plot.addItem(rect)
        return rect

    def _clear_picks(self):
        for attr in ("_pick_overlay_a", "_pick_overlay_b"):
            o = getattr(self, attr, None)
            if o is not None:
                try:
                    self.plot.removeItem(o)
                except Exception:
                    pass
            setattr(self, attr, None)
        self._picked_a = None
        self._picked_b = None

    def _update_pick_label(self):
        u = self.unit_label
        s = self.unit_scale
        if self._picked_a is None:
            self.pick_label.setText("Pick span A (click a bar)")
            return
        a = self._picked_a
        if self._picked_b is None:
            self.pick_label.setText(
                f"<b>A:</b> {a['name']} "
                f"[{(a['start_us']-self.t_min)*s:.3f} to {(a['end_us']-self.t_min)*s:.3f} {u}]"
                f" &nbsp;&nbsp; - &nbsp;&nbsp; now pick span B"
            )
            return
        b = self._picked_b
        a_start = (a["start_us"] - self.t_min) * s
        a_end = (a["end_us"] - self.t_min) * s
        b_start = (b["start_us"] - self.t_min) * s
        b_end = (b["end_us"] - self.t_min) * s

        gap = (b["start_us"] - a["end_us"]) * s
        start_to_start = (b["start_us"] - a["start_us"]) * s
        full = (b["end_us"] - a["start_us"]) * s

        self.pick_label.setText(
            f"<b>A:</b> {a['name']} [{a_start:.3f} - {a_end:.3f} {u}]   "
            f"<b>B:</b> {b['name']} [{b_start:.3f} - {b_end:.3f} {u}]<br>"
            f"<b>A -&gt; B gap:</b> {gap:.3f} {u}   "
            f"<b>start -&gt; start:</b> {start_to_start:.3f} {u}   "
            f"<b>A.start -&gt; B.end:</b> {full:.3f} {u}"
        )

    # ── Navigation actions ───────────────────────────────────────────

    def _on_search_activated(self, idx):
        if idx < 0:
            return
        name = self.search_combo.itemText(idx)
        if name:
            self._jump_to_function_name(name)

    def _on_search_return_pressed(self):
        """Enter key in the Find combobox — jump to (or advance through)
        whatever the user typed."""
        text = self.search_combo.currentText().strip()
        if not text:
            return
        if text in self.func_names:
            self._jump_to_function_name(text)
        else:
            self.statusBar().showMessage(f"No function named '{text}'", 3000)

    def _update_search_completer(self):
        """Refresh the Find combo's completer with the current func_names.

        Called whenever spans change (refresh or Open Trace) so the
        autocomplete list stays in sync.
        """
        if hasattr(self, "_search_completer") and self._search_completer is not None:
            model = QtCore.QStringListModel(list(self.func_names), self._search_completer)
            self._search_completer.setModel(model)

    def _jump_to_function_name(self, name):
        """Center on the next occurrence of ``name``, cycling through matches."""
        matches = sorted(
            [sp for sp in self.spans if sp["name"] == name],
            key=lambda s: s["start_us"],
        )
        if not matches:
            return

        c = self._iter_cursor
        if c["kind"] == "function" and c["name"] == name:
            c["index"] = (c["index"] + 1) % len(matches)
        else:
            c["kind"] = "function"
            c["name"] = name
            c["index"] = 0

        sp = matches[c["index"]]
        center = (sp["start_us"] + sp["end_us"]) / 2 - self.t_min
        self.view_start = max(0, center - self.window_us / 2)
        self._update_view_range()
        self._flash_span_highlight(sp)
        self._show_iter_status(name, c["index"] + 1, len(matches), sp["start_us"] - self.t_min)

    def _on_ribbon_requested(self, name):
        """Context menu: Show in Ribbon View → pin a ribbon for ``name``."""
        if hasattr(self, "ribbon_dock") and self.ribbon_dock is not None:
            self.ribbon_dock.add_function(name)
            self.ribbon_dock.show()
            self.ribbon_dock.raise_()

    def _on_ribbon_tick_clicked(self, name, start_us):
        """A tick inside a ribbon row was clicked — centre the main chart
        on that exact span occurrence, keeping current zoom width, then
        flash the span so the user sees where it is.

        Uses a one-shot flash (like Top-N's click path) rather than
        ``set_highlighted_name`` — the latter is persistent and dims every
        other bar on the chart, which has no obvious way to exit.
        """
        rel_start = start_us - self.t_min
        new_start = max(0.0, rel_start - self.window_us / 2)
        max_start = max(0.0, self.total_us - self.window_us)
        self.view_start = min(new_start, max_start)
        self._update_view_range()
        # Find the actual span dict for a proper flash rectangle
        for sp in self.spans:
            if sp["name"] == name and sp["start_us"] == start_us:
                self._flash_span_highlight(sp)
                break

    def _jump_to_span_instance(self, sp):
        """Center on a specific span instance (used by the Top-N dock)."""
        if not sp:
            return
        center = (sp["start_us"] + sp["end_us"]) / 2 - self.t_min
        self.view_start = max(0, center - self.window_us / 2)
        self._update_view_range()
        self._flash_span_highlight(sp)
        u = self.unit_label
        s = self.unit_scale
        self.statusBar().showMessage(
            f"{sp['name']}  duration={sp['duration_us'] * s:.3f} {u}  "
            f"@ {(sp['start_us'] - self.t_min) * s:.3f} {u}",
            4000,
        )
        QtCore.QTimer.singleShot(4100, self._update_status_bar)

    def _jump_to_mark_name(self, name):
        """Center on the next occurrence of a marker, cycling through matches."""
        matches = sorted(
            [m for m in self.marks if m["name"] == name],
            key=lambda m: m["t_us"],
        )
        if not matches:
            return

        c = self._iter_cursor
        if c["kind"] == "mark" and c["name"] == name:
            c["index"] = (c["index"] + 1) % len(matches)
        else:
            c["kind"] = "mark"
            c["name"] = name
            c["index"] = 0

        mk = matches[c["index"]]
        center = mk["t_us"] - self.t_min
        self.view_start = max(0, center - self.window_us / 2)
        self._update_view_range()
        self._flash_mark_highlight(mk)
        self._show_iter_status(name, c["index"] + 1, len(matches), mk["t_us"] - self.t_min)

    def _show_iter_status(self, name, index, total, t_rel_us):
        """Show `foo (3/10) @ 1.234 ms` in the status bar for 4 seconds."""
        u = self.unit_label
        s = self.unit_scale
        msg = f"{name}  ({index}/{total})    @ {t_rel_us * s:.3f} {u}"
        self.statusBar().showMessage(msg, 4000)
        # Restore the default status line 100 ms after the timed message expires
        QtCore.QTimer.singleShot(4100, self._update_status_bar)

    # ── Iteration highlight overlay ─────────────────────────────────

    def _flash_highlight_rect(self, x_rel, y, width, height):
        """Draw a high-contrast outlined rectangle that pulses then fades.

        Uses a thick white outline so it stays visible regardless of the
        underlying bar color (the palette includes yellow shades that would
        hide a yellow highlight). A short alternating pulse (white <-> red)
        catches the eye, then the rectangle settles into a steady white
        outline for a moment before being removed.

        Removes any previous highlight first so successive iterations don't
        accumulate overlays.
        """
        self._clear_iter_highlight()

        rect = QtWidgets.QGraphicsRectItem(x_rel, y, max(width, 1e-6), height)
        # Slight dark dim over the bar so the outline pops
        fill = QtGui.QColor(0, 0, 0, 90)
        rect.setBrush(QtGui.QBrush(fill))

        pen = QtGui.QPen(QtGui.QColor("#ffffff"))
        pen.setWidth(3)
        pen.setCosmetic(True)  # 3 screen pixels regardless of zoom
        rect.setPen(pen)
        rect.setZValue(200)
        self.plot.addItem(rect)
        self._iter_highlight_item = rect

        # Pulse animation: alternate outline color white <-> red 6 times
        # (≈ 720 ms of attention-grabbing flashing), then steady white for
        # another 1.2 s, then remove. Total visible time ≈ 1.9 s.
        self._iter_highlight_step = 0
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._iter_highlight_tick)
        timer.start(120)
        self._iter_highlight_timer = timer

    def _iter_highlight_tick(self):
        """Pulse the highlight outline color, then settle, then remove."""
        if self._iter_highlight_item is None:
            return
        self._iter_highlight_step += 1
        step = self._iter_highlight_step

        if step <= 6:
            # Alternate red <-> white outline
            color = "#ff3030" if (step % 2 == 1) else "#ffffff"
            pen = self._iter_highlight_item.pen()
            pen.setColor(QtGui.QColor(color))
            pen.setWidth(3)
            pen.setCosmetic(True)
            self._iter_highlight_item.setPen(pen)
        elif step >= 16:
            # Done — clean up (≈ 6×120 ms pulse + 10×120 ms steady = 1.92 s)
            self._clear_iter_highlight()

    def _flash_span_highlight(self, sp):
        """Highlight an instrumented span (handles ISR display lane)."""
        x_rel = sp["start_us"] - self.t_min
        if sp.get("ipsr", 0) == 0:
            y = sp["depth"]
        else:
            y = -(sp["depth"] + 1)
        self._flash_highlight_rect(x_rel, y, sp["duration_us"], ROW_HEIGHT)

    def _flash_mark_highlight(self, mk):
        """Highlight a TRACE_MARK by lighting up its line, not a vertical band."""
        x_rel = mk["t_us"] - self.t_min
        y_top = self.min_display_y - 0.2
        y_bot = self.max_display_y + 1.0
        self._flash_highlight_line(x_rel, y_top, y_bot)

    def _flash_highlight_line(self, x_rel, y_top, y_bot):
        """Draw a thick cosmetic vertical line that pulses then fades.

        Used for marker iteration (no vertical box). Reuses the existing
        pulse animation by storing a QGraphicsLineItem in _iter_highlight_item.
        """
        self._clear_iter_highlight()

        line = QtWidgets.QGraphicsLineItem(x_rel, y_top, x_rel, y_bot)
        pen = QtGui.QPen(QtGui.QColor("#ffffff"))
        pen.setWidth(4)
        pen.setCosmetic(True)
        line.setPen(pen)
        line.setZValue(200)
        self.plot.addItem(line)
        self._iter_highlight_item = line

        # Reuse the same pulse loop the rectangle uses
        self._iter_highlight_step = 0
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._iter_highlight_tick)
        timer.start(120)
        self._iter_highlight_timer = timer

    def _clear_iter_highlight(self):
        if self._iter_highlight_item is not None:
            try:
                self.plot.removeItem(self._iter_highlight_item)
            except Exception:
                pass
            self._iter_highlight_item = None
        if self._iter_highlight_timer is not None:
            self._iter_highlight_timer.stop()
            self._iter_highlight_timer = None
        self._iter_highlight_step = 0

    def _iter_next(self):
        """F3 — advance the current iterator cursor (same function/mark)."""
        c = self._iter_cursor
        if c["kind"] is None or c["name"] is None:
            return
        # Re-call the same jump method, which auto-advances since the
        # kind+name match.
        if c["kind"] == "function":
            self._jump_to_function_name(c["name"])
        else:
            self._jump_to_mark_name(c["name"])

    def _iter_prev(self):
        """Shift+F3 — step the cursor backwards with wrap-around."""
        c = self._iter_cursor
        if c["kind"] is None or c["name"] is None:
            return
        if c["kind"] == "function":
            matches = sorted(
                [sp for sp in self.spans if sp["name"] == c["name"]],
                key=lambda s: s["start_us"],
            )
            if not matches:
                return
            c["index"] = (c["index"] - 2) % len(matches)  # -2 because _jump adds +1
            self._jump_to_function_name(c["name"])
        else:
            matches = sorted(
                [m for m in self.marks if m["name"] == c["name"]],
                key=lambda m: m["t_us"],
            )
            if not matches:
                return
            c["index"] = (c["index"] - 2) % len(matches)
            self._jump_to_mark_name(c["name"])

    def _on_mark_visibility_changed(self, hidden_set):
        """Propagate hidden marker names to the flame chart and minimap."""
        if hasattr(self, "_flame_item") and self._flame_item is not None:
            self._flame_item.set_hidden_marks(hidden_set)
        if hasattr(self, "minimap"):
            self.minimap.set_hidden_marks(hidden_set)

    def _show_jitter_for_function(self, name):
        """Open the JitterDialog for a function. Uses span start_us as event times."""
        times = sorted(sp["start_us"] for sp in self.spans if sp["name"] == name)
        if len(times) < 2:
            QtWidgets.QMessageBox.information(
                self,
                "Period / Jitter",
                f"'{name}' has only {len(times)} occurrence(s). "
                "Need at least 2 to compute periods.",
            )
            return
        dlg = JitterDialog(name, times, self.unit_label, self.unit_scale, parent=self)
        dlg.exec()

    def _show_jitter_for_marker(self, name):
        """Open the JitterDialog for a marker. Uses mark t_us as event times."""
        times = sorted(m["t_us"] for m in self.marks if m["name"] == name)
        if len(times) < 2:
            QtWidgets.QMessageBox.information(
                self,
                "Period / Jitter",
                f"Marker '{name}' has only {len(times)} occurrence(s). "
                "Need at least 2 to compute periods.",
            )
            return
        dlg = JitterDialog(name, times, self.unit_label, self.unit_scale, parent=self)
        dlg.exec()

    def _reset_view(self):
        self.window_us = min(DEFAULT_WINDOW_US, self.total_us) if self.total_us > 0 else 1.0
        self.window_spin.blockSignals(True)
        self.window_spin.setValue(self.window_us * self.unit_scale)
        self.window_spin.blockSignals(False)
        self.view_start = 0.0
        self._update_view_range()

    # ── Hover handling ───────────────────────────────────────────────

    def _on_mouse_moved(self, pos):
        self._last_mouse_pos = pos
        if not self._hover_timer.isActive():
            self._hover_timer.start()

    def _do_hover_update(self):
        pos = self._last_mouse_pos
        if pos is None:
            return
        vb = self.plot.getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            return

        mouse_pt = vb.mapSceneToView(pos)
        x_rel = mouse_pt.x()
        y = mouse_pt.y()
        depth = int(y)

        hit = self._find_span_at(depth, x_rel, y)
        self._last_hit = hit

        # Mark hover detection — tolerance is 5 px in current X transform
        self._last_mark = None
        if hasattr(self, "_flame_item") and self._flame_item is not None:
            # Convert 5 pixels → data units using the view box mapping
            vb_rect = vb.viewRect()
            px_per_unit = vb.width() / max(vb_rect.width(), 1e-9)
            if px_per_unit > 0:
                tolerance = 5.0 / px_per_unit
                self._last_mark = self._flame_item.nearest_mark(x_rel, tolerance)

        # Pause region hover detection — checks whether the cursor is inside
        # a paused interval
        self._last_pause = self._find_pause_at(x_rel)

        self._refresh_hover_label()
        self._refresh_sticky_hover_text()

        # Highlight all instances of the hovered function
        if self.highlight_hover_enabled and hasattr(self, "_flame_item") and self._flame_item is not None:
            self._flame_item.set_highlighted_name(hit["name"] if hit else None)

    def _refresh_sticky_hover_text(self):
        """Push a short ``name  duration`` string into the flame item for
        the sticky in-chart hover pill. No-op if the toggle is off."""
        if not hasattr(self, "_flame_item") or self._flame_item is None:
            return
        if not getattr(self, "act_sticky_hover", None) or not self.act_sticky_hover.isChecked():
            return
        u = self.unit_label
        s = self.unit_scale
        hit = getattr(self, "_last_hit", None)
        if hit:
            txt = f"{hit['name']}   {hit['duration_us'] * s:.3f} {u}"
        else:
            txt = ""
        self._flame_item.set_sticky_text(txt)

    def _find_pause_at(self, x_rel):
        """Return the pause region that contains the cursor's X, or None."""
        x_abs = x_rel + self.t_min
        for r in self.pause_regions:
            if r["start_us"] <= x_abs <= r["end_us"]:
                return r
        return None

    def _refresh_hover_label(self):
        u = self.unit_label
        s = self.unit_scale

        # Pause region takes priority — show "PAUSED" details when over a band
        pause = getattr(self, "_last_pause", None)
        if pause is not None:
            start_rel = (pause["start_us"] - self.t_min) * s
            end_rel = (pause["end_us"] - self.t_min) * s
            dur = (pause["end_us"] - pause["start_us"]) * s
            self.hover_label.setText(
                f"<b>PAUSED</b>  |  "
                f"Start: {start_rel:.3f} {u}  |  "
                f"End: {end_rel:.3f} {u}  |  "
                f"Duration: {dur:.3f} {u}"
            )
            return

        # Marks take precedence in the hover label — they're the rarer event
        mark = getattr(self, "_last_mark", None)
        if mark is not None:
            # nearest_mark returns flame-internal form ({"x","name","ipsr"});
            # raw marks use ("t_us","name","ipsr"). Handle both.
            if "x" in mark:
                t_rel = mark["x"]
            else:
                t_rel = mark["t_us"] - self.t_min
            t = t_rel * s
            ctx = f" (ISR {mark['ipsr']})" if mark.get("ipsr", 0) else ""
            self.hover_label.setText(
                f"<b>MARK:</b> <span style='color:#00ddff'>{mark['name']}</span>"
                f"  @ {t:.3f} {u}{ctx}"
            )
            return

        hit = getattr(self, "_last_hit", None)
        if not hit:
            self.hover_label.setText("Hover over a bar to see details")
            return
        ipsr = hit.get("ipsr", 0)
        ctx = f"  |  ISR {ipsr}" if ipsr else ""
        self.hover_label.setText(
            f"<b>{hit['name']}</b>  |  "
            f"Duration: {hit['duration_us'] * s:.3f} {u}  |  "
            f"Start: {(hit['start_us'] - self.t_min) * s:.3f} {u}  |  "
            f"End: {(hit['end_us'] - self.t_min) * s:.3f} {u}  |  "
            f"Depth: {hit['depth']}  |  "
            f"Addr: 0x{hit['addr']:08X}"
            + ctx
        )

    def _find_span_at(self, depth, x_rel, y):
        """Locate a span under the cursor, accounting for thread + ISR lanes."""
        x_abs = x_rel + self.t_min
        # Thread lane hit: depth >= 0 and within ROW_HEIGHT of a depth row
        if depth >= 0 and (depth <= y <= depth + ROW_HEIGHT):
            for sp in self.spans:
                if sp.get("ipsr", 0) != 0:
                    continue
                if sp["depth"] != depth:
                    continue
                if sp["start_us"] <= x_abs <= sp["end_us"]:
                    return sp
            return None

        # ISR lane hit: y negative. display_y = -(depth + 1) → depth_isr = -int(y)-1
        if y < 0:
            isr_depth = -int(y + 1) - 0  # floor for negative y
            # More precise: invert display_y = -(depth+1) so depth = -display_y - 1
            # display_y in [-(d+1), -d) → depth d
            # Easiest: iterate ISR spans and check geometry
            for sp in self.spans:
                if sp.get("ipsr", 0) == 0:
                    continue
                disp_y = -(sp["depth"] + 1)
                if disp_y <= y <= disp_y + ROW_HEIGHT:
                    if sp["start_us"] <= x_abs <= sp["end_us"]:
                        return sp
        return None


_ICON_PATH = os.path.join(os.path.dirname(__file__), "icons", "icon.png")


def _apply_dark_title_bar(widget):
    """Force the Windows native title bar into dark mode so it matches
    the rest of the UI. No-op on non-Windows platforms or older Windows
    versions that don't support the DWM attribute."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20          # Windows 10 20H1+
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19      # older builds
        value = ctypes.c_int(1)
        dwmapi = ctypes.windll.dwmapi
        # Try the current attribute first; fall back to the legacy one
        # on older Windows 10 builds.
        res = dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if res != 0:
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
    except Exception:
        # Dark title bar is cosmetic; never let it block startup.
        pass


def show_gui(
    spans,
    marks=None,
    pause_regions=None,
    wrapped=False,
    refresh_fn=None,
    elf_path=None,
    cpu_mhz=96.0,
):
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    # Application icon — shown in the taskbar, window title bar, and
    # Alt+Tab switcher.
    if os.path.exists(_ICON_PATH):
        icon = QtGui.QIcon(_ICON_PATH)
        app.setWindowIcon(icon)
    else:
        icon = None
    win = ProfilerWindow(
        spans,
        marks=marks,
        pause_regions=pause_regions,
        wrapped=wrapped,
        refresh_fn=refresh_fn,
        elf_path=elf_path,
        cpu_mhz=cpu_mhz,
    )
    if icon is not None:
        win.setWindowIcon(icon)
    win.show()
    # Apply dark title bar AFTER show() — DWM needs a valid HWND.
    _apply_dark_title_bar(win)
    app.exec()
