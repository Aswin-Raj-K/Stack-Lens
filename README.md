# CortexM0 Profiler

A real-time flame-chart profiler for ARM Cortex-M0 targets.  Reads trace data
from a J-Link debug probe (or a saved `.json` trace) and renders an interactive
call-depth timeline.

## Requirements

- Python 3.10+
- See `requirements.txt` (PySide6, pyqtgraph, numpy, pylink-square)

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python profiler.py
```

Or open a saved trace directly:

```bash
python profiler.py path/to/trace.json
```

## Keyboard shortcuts

Press `?` inside the profiler for a full shortcut reference.

## Project layout

```
profiler.py          # entry point
span_builder.py      # converts raw trace samples into call-span objects
trace_io.py          # JSON import / CSV+JSON export
trace_reader.py      # J-Link live capture

gui/
  main_window.py     # ProfilerWindow — the main application window
  axes.py            # UnitAxis (µs↔ms tick labels), DepthAxis
  cursor_handle.py   # Draggable grab-tab for measurement cursors
  event_filters.py   # App-level key filters (+/−zoom, ? overlay)
  dock_base.py       # DockBase — common set_unit/refresh_theme API
  flame_item.py      # pyqtgraph GraphicsObject that draws call bars
  minimap_widget.py  # Scrollable overview strip
  summary_dock.py    # Function stats table
  call_tree_dock.py  # Hierarchical call tree
  marker_dock.py     # Named time markers
  top_n_dock.py      # Top-N slowest functions
  call_graph_dock.py # Caller/callee graph
  ribbon_dock.py     # Per-function execution ribbon
  jitter_dialog.py   # Period/jitter analysis dialog
  settings_dialog.py # Appearance & preferences
  shortcut_overlay.py# ? keyboard cheat-sheet overlay
  theme.py           # Design tokens; apply_theme()
  constants.py       # Colors, stylesheet, geometry constants
  themes/            # JSON palette files (dark.json, light.json, …)
  icons/             # SVG icons
```
