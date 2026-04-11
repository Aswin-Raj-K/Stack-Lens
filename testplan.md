# Capture Function Parameter Values in the Profiler Trace

## Context

The current tracer uses GCC's `-finstrument-functions`, which only tells us
*when* a function was entered/exited, not *what arguments it was called with*.
The user wants to see parameter values in the flame chart — e.g. knowing that
`handle_service_start(desc_id=3)` rather than just `handle_service_start`.

Why auto-capture from the hook doesn't work:
`__cyg_profile_func_enter(this_fn, caller)` is called at the *beginning* of a
function's prologue, but by the time the hook runs, GCC has already configured
r0/r1 to the hook's own args. The target function's original r0-r3 are either
clobbered, spilled to an unknown stack slot, or reordered by optimisation. No
amount of naked-assembly cleverness recovers this reliably for args 0/1, and
args 2/3 only survive by accident. See the `Plan agent` analysis in this
conversation — approach A was rejected.

Instead we add a **manual value-logging macro** that the user places at the top
of any function they care about. It composes cleanly with the existing
auto-instrumentation — nothing about enter/exit tracking changes.

## Approach

Extend `TraceEvent` to 16 bytes with a new `value` field and a new event type
`2 = value`. Provide a `TRACE_VAL(x)` macro that records
`{cyccnt, __func__ pointer, value}` into the existing ring buffer. The profiler
renders type-2 events as labelled markers attached to the enclosing flame bar.

- **Reliable** — the compiler materialises `x` into whatever register the
  helper needs, guaranteeing capture.
- **Zero cost** where unused — functions the user doesn't annotate still get
  their normal enter/exit trace and nothing more.
- **Backward compatible** — the profiler's existing `build_spans` logic keeps
  working on type 0/1 events; it just needs to skip type 2 when pairing.

## Firmware Changes

### [app/ptt_common/trace.cpp](d:/Projects/QS127S_2/FW-APP-QS127S-audio/app/ptt_common/trace.cpp)

1. Extend the struct to 16 bytes (stays 4-byte aligned, so TCM math is still
   clean):

   ```cpp
   struct TraceEvent {
       uint8_t  type;        // 0=enter, 1=exit, 2=value
       uint8_t  _pad[3];
       uint32_t cyccnt;
       uint32_t context;     // func_addr (enter/exit) OR __func__ pointer (value)
       uint32_t value;       // 0 for enter/exit; logged value for type 2
   };
   ```

2. Bump `trace_buf` to `TraceEvent trace_buf[1024]` — same count, new size.
   Total TCM footprint goes from 12 KB → 16 KB.

3. Update the existing `trace_log(func, type)` to also zero the new `value`
   field for enter/exit events.

4. Add a new `trace_value_log(const char *name, uint32_t value)` helper that
   writes a type-2 event. Mark it `no_instrument_function` so it doesn't trace
   itself.

### [app/ptt_common/trace.hpp](d:/Projects/QS127S_2/FW-APP-QS127S-audio/app/ptt_common/trace.hpp) (new file)

Public header exposing the macro. Needs to be includable from any C/C++ file
that wants to log values:

```cpp
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void trace_init(void);
void trace_value_log(const char *name, uint32_t value);

#ifdef __cplusplus
}
#endif

#define TRACE_VAL(x)            trace_value_log(__func__, (uint32_t)(x))
#define TRACE_VAL_NAMED(tag, x) trace_value_log((tag), (uint32_t)(x))
```

The user replaces implicit `extern void trace_init();` declarations in
`app/ptt_common/fsm.cpp` (line 26) and `app/Trace_Test/main.cpp` with
`#include "trace.hpp"`.

## Profiler Changes (D:\Projects\Profiler)

### [trace_reader.py](D:/Projects/Profiler/trace_reader.py)

- `TRACE_EVENT_SIZE = 16` (was 12)
- `EVENT_FMT = "<BxxxIII"` — adds a third uint32
- Add a `read_string_at(jlink, addr, max_len=64)`: read bytes until null
  terminator. Cache by address.
- Also preload `.rodata` bytes from the ELF so string literals can be resolved
  offline without another J-Link round trip. Use `elf.get_section_by_name('.rodata')`
  or iterate sections looking for one containing the target address.

### [span_builder.py](D:/Projects/Profiler/span_builder.py)

- `parse_events`: unpack the extra `value` field; emit dicts as
  `{"type", "cyccnt", "addr", "value"}`.
- `resolve_names`: for `type == 2`, look up `addr` as a C-string pointer
  (rodata lookup → demangle is a no-op on plain strings, just use as-is).
- `build_spans`: **skip** type-2 events when matching enter/exit pairs, but
  collect them into a parallel list `value_events = [{t_us, name, value}]`
  and return both. Returning spans becomes `(spans, value_events)`.
- `print_summary`: unchanged (value events are side-channel).

### [gui/flame_item.py](D:/Projects/Profiler/gui/flame_item.py)

- Accept `value_events` in the constructor and bucket them by their enclosing
  span (bisect by time into the deepest span that contains the event).
- In `paint()`: draw a small triangle/diamond marker at the top of each span
  for each associated value event, with a short inline label (`name=42`) if
  the bar is wide enough.

### [gui/main_window.py](D:/Projects/Profiler/gui/main_window.py)

- Thread `value_events` through from `show_gui(spans, value_events)` →
  `ProfilerWindow` → `FlameItem`.
- Extend the hover label to also show any value events inside the hovered
  span: `"handle_fifo_read  |  desc_id=3, size=72"`.

### [profiler.py](D:/Projects/Profiler/profiler.py)

- Pass the ELF file + J-Link handle through to `resolve_names` for rodata
  lookup.
- Call `spans, values = build_spans(...)` and hand both to `show_gui`.

## Example Usage (for the user)

```cpp
#include "trace.hpp"

static void handle_service_start(uint8_t desc_id)
{
    TRACE_VAL(desc_id);   // appears as "desc_id=3" in the flame chart
    // ...
}

static void handle_fifo_read(uint8_t desc_id, const void* args)
{
    TRACE_VAL(desc_id);
    // ...
}
```

Any function left unannotated still shows up via auto-instrumentation — this
is purely additive.

## Verification

1. **Firmware compiles cleanly** — build `app/Trace_Test/` and
   `app/ptt_v2_device_radio/` with the extended `TraceEvent` struct. Confirm
   TCM usage in the linker's `--print-memory-usage` report went up by ≤ 4 KB.
2. **Size sanity** — `arm-none-eabi-nm executable.elf | grep trace_buf`
   should report a symbol 16384 bytes long (1024 × 16).
3. **End-to-end test on Trace_Test** — add `TRACE_VAL(i)` inside
   `process_sample(uint32_t sample)` in `app/Trace_Test/main.cpp`. Flash,
   run past `trace_init()`, break on `while(1)`, run profiler. Expect to
   see `sample=0` .. `sample=4` markers inside each `process_sample` span
   in the flame chart.
4. **Backward-compat check** — verify that functions *without* any
   `TRACE_VAL()` calls still show up as bars with correct timing (i.e. the
   enter/exit path is untouched).
5. **Hover test** — hover over a `process_sample` bar in the GUI and confirm
   the hover label reports the captured value.

## Critical Files

- [app/ptt_common/trace.cpp](d:/Projects/QS127S_2/FW-APP-QS127S-audio/app/ptt_common/trace.cpp) — struct + helper
- [app/ptt_common/trace.hpp](d:/Projects/QS127S_2/FW-APP-QS127S-audio/app/ptt_common/trace.hpp) — **new**, public header with the macro
- [app/ptt_common/fsm.cpp:26](d:/Projects/QS127S_2/FW-APP-QS127S-audio/app/ptt_common/fsm.cpp#L26) — replace `extern void trace_init();` with `#include "trace.hpp"`
- [app/Trace_Test/main.cpp](d:/Projects/QS127S_2/FW-APP-QS127S-audio/app/Trace_Test/main.cpp) — same replacement + demo `TRACE_VAL`
- [D:/Projects/Profiler/trace_reader.py](D:/Projects/Profiler/trace_reader.py)
- [D:/Projects/Profiler/span_builder.py](D:/Projects/Profiler/span_builder.py)
- [D:/Projects/Profiler/gui/flame_item.py](D:/Projects/Profiler/gui/flame_item.py)
- [D:/Projects/Profiler/gui/main_window.py](D:/Projects/Profiler/gui/main_window.py)
- [D:/Projects/Profiler/profiler.py](D:/Projects/Profiler/profiler.py)

---

# Profiler GUI: Summary Search + Zoom-to-Selection

## Context

Two navigation pain points as traces grow larger:

1. **Finding a specific function in the summary dock is hard** once the trace
   has 100+ unique functions. The user has to scroll through a wall of rows
   to find the one they care about.

2. **Zooming into a specific time window requires multiple manual steps**:
   read an approximate start time off the axis, type it into the "Jump to"
   spinbox, estimate a width, type it into the "Window" spinbox, click Apply.
   Natural UX is to simply drag-select a region on the chart.

Both features are purely client-side GUI enhancements — no changes to the
firmware, linker script, trace format, or span parsing.

## Feature 1: Summary dock search bar

### Design

Add a `QLineEdit` in the existing top button row of
[gui/summary_dock.py](D:/Projects/Profiler/gui/summary_dock.py). Live filter
as the user types: any row whose function name doesn't contain the query
substring (case-insensitive) gets hidden via `QTableWidget.setRowHidden()`.

- **Clear button** built into the line edit via
  `setClearButtonEnabled(True)` — one-click reset.
- **Placeholder text**: `"Search functions..."`
- **Keyboard shortcut**: Ctrl+F focuses the search box (add a `QShortcut`
  bound to the dock).
- **Persistence across refreshes**: store the current query in
  `self._search_text`. When `set_spans()` rebuilds the table, re-apply the
  filter so the user's filter survives a J-Link refresh.
- **Filter interaction with show/hide checkboxes**: filter is purely visual
  (hides rows); it does NOT affect the `hidden_names` set emitted via
  `visibility_changed`. Hiding a row via the filter does not hide its bars
  on the flame chart.

### Implementation sketch (in `SummaryDock`)

```python
self._search_text = ""

# In _build_ui, in the existing btn_row:
self.search_edit = QtWidgets.QLineEdit()
self.search_edit.setPlaceholderText("Search functions...")
self.search_edit.setClearButtonEnabled(True)
self.search_edit.textChanged.connect(self._on_search_changed)
btn_row.addWidget(self.search_edit, 1)  # stretch

def _on_search_changed(self, text):
    self._search_text = text.lower()
    self._apply_filter()

def _apply_filter(self):
    q = self._search_text
    for row in range(self._table.rowCount()):
        name = self._row_names[row].lower() if row < len(self._row_names) else ""
        self._table.setRowHidden(row, bool(q) and q not in name)

# In set_spans(), at the end:
self._apply_filter()
```

### Files changed

- [D:/Projects/Profiler/gui/summary_dock.py](D:/Projects/Profiler/gui/summary_dock.py) — add QLineEdit, `_apply_filter()`, wire in `set_spans()`

---

## Feature 2: Zoom to Selection (drag to select a time window)

### Design — dedicated mode via toolbar button

A toggle action **"Zoom to Selection" (Ctrl+R)** on the View menu and as a
toolbar button. When active:

1. The plot cursor changes to a crosshair.
2. Left-click starts a selection at the click's X coordinate (in data units).
3. Dragging extends the selection; a translucent yellow vertical band
   (`pg.LinearRegionItem` with `movable=False`) tracks between the start X
   and the current cursor X, spanning the full depth range.
4. On left-button release:
   - If the selection width is > 1 data unit, set
     `view_start = min_x`, `window_us = width`, sync the window spinbox,
     and call `_update_view_range()` to apply.
   - Clean up the overlay, uncheck the toolbar action (one-shot mode so
     the user doesn't accidentally stay in select mode).
5. **Escape key** cancels an in-progress selection and exits the mode.

### Why a mode and not Shift+drag

Shift+drag would be cleaner for power users but conflicts in muscle memory
with Shift+wheel (already mapped to "pan faster"). A dedicated toggle is
more discoverable and matches the pattern used by Chrome DevTools Performance
tab and Wireshark. Ctrl+R ("Range") is the shortcut.

### Why override `QGraphicsView` methods instead of scene signals

pyqtgraph's `scene().sigMouseClicked` only fires on a complete press+release
without movement (a click), not a drag. The scene doesn't expose
press/move/release separately. The clean approach is to override
`QGraphicsView.mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent` on
the `plot_widget` — matching the existing pattern already used for
`wheelEvent` at
[gui/main_window.py:~115](D:/Projects/Profiler/gui/main_window.py).

Preserve a reference to the original methods so non-select-mode behavior
falls through unchanged (pick-spans clicks, measurement-cursor drags, etc.):

```python
self._orig_mouse_press  = self.plot_widget.mousePressEvent
self._orig_mouse_move   = self.plot_widget.mouseMoveEvent
self._orig_mouse_release = self.plot_widget.mouseReleaseEvent

self.plot_widget.mousePressEvent  = self._plot_mouse_press
self.plot_widget.mouseMoveEvent   = self._plot_mouse_move
self.plot_widget.mouseReleaseEvent = self._plot_mouse_release
```

### Overlay choice

Use `pg.LinearRegionItem` with:
- `movable=False` (so the user can't accidentally drag the handles mid-selection)
- `brush=(255, 200, 0, 60)` — translucent amber
- `pen=mkPen("#ffcc00", width=1)` — thin yellow border
- `zValue=50` — above the flame item, below the measurement cursors

LinearRegionItem automatically spans the full y-range of the view, which is
exactly what we want.

### Interaction with existing features

- **Measurement cursors** (draggable InfiniteLines): they intercept their own
  mouse events via the Qt item system, so they still work when the user
  clicks directly on a cursor line. If the cursor is inside a selection
  drag, Qt gives item events priority — fine.
- **Pick-spans mode** (click a bar to highlight): uses `sigMouseClicked`
  which fires only on clicks without movement. Drag-to-zoom won't trigger
  it.
- **Hover highlighting** (`_on_mouse_moved` via `sigMouseMoved`): still
  fires during drag, but the overlay is the visible feedback, so extra
  hover highlight is harmless. Can suppress it during drag if it's
  distracting.
- **Window spinbox / scrollbar**: after applying, `_update_view_range()`
  already syncs both.

### State held by ProfilerWindow

```python
self._select_mode = False        # toolbar action is checked
self._select_start_x = None      # absolute us, or None if not dragging
self._select_overlay = None      # pg.LinearRegionItem during drag
```

### Pseudocode for the handlers

```python
def _toggle_select_zoom(self, checked):
    self._select_mode = checked
    if checked:
        self.plot_widget.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage(
            "Drag horizontally on the chart, release to zoom. Esc to cancel.",
            0,  # persistent
        )
    else:
        self.plot_widget.unsetCursor()
        self._cancel_select_overlay()
        self.statusBar().clearMessage()
        self._update_status_bar()  # restore the default message

def _plot_mouse_press(self, event):
    if self._select_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
        vp = self._view_x_from_event(event)
        self._select_start_x = vp
        self._select_overlay = pg.LinearRegionItem(
            values=[vp, vp], movable=False,
            brush=(255, 200, 0, 60),
            pen=pg.mkPen("#ffcc00", width=1),
        )
        self._select_overlay.setZValue(50)
        self.plot.addItem(self._select_overlay)
        event.accept()
        return
    self._orig_mouse_press(event)

def _plot_mouse_move(self, event):
    if self._select_mode and self._select_start_x is not None:
        vp = self._view_x_from_event(event)
        self._select_overlay.setRegion([self._select_start_x, vp])
        event.accept()
        return
    self._orig_mouse_move(event)

def _plot_mouse_release(self, event):
    if (
        self._select_mode
        and self._select_start_x is not None
        and event.button() == QtCore.Qt.MouseButton.LeftButton
    ):
        vp = self._view_x_from_event(event)
        x1 = max(0.0, min(self._select_start_x, vp))
        x2 = min(self.total_us, max(self._select_start_x, vp))
        width = x2 - x1
        self._cancel_select_overlay()

        if width >= max(1e-3, 1e-6 * self.total_us):
            self.view_start = x1
            self.window_us = width
            self.window_spin.blockSignals(True)
            self.window_spin.setValue(width * self.unit_scale)
            self.window_spin.blockSignals(False)
            self._update_view_range()

        # Auto-exit select mode (one-shot)
        self.act_select_zoom.setChecked(False)
        self._toggle_select_zoom(False)
        event.accept()
        return
    self._orig_mouse_release(event)

def _view_x_from_event(self, event):
    """Map a QMouseEvent's position to data-coordinate X."""
    vb = self.plot.getViewBox()
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
    if event.key() == QtCore.Qt.Key.Key_Escape and self._select_mode:
        self.act_select_zoom.setChecked(False)
        self._toggle_select_zoom(False)
        event.accept()
        return
    super().keyPressEvent(event)
```

### Files changed

- [D:/Projects/Profiler/gui/main_window.py](D:/Projects/Profiler/gui/main_window.py) — new menu action, toolbar button, state fields, mouse overrides, `_cancel_select_overlay()`, `keyPressEvent()` override

## Verification

### Feature 1 (search bar)

1. Launch the profiler on a trace with ≥10 unique functions
2. Type a substring (e.g. `proc`) in the search box → only matching rows remain visible
3. Clear via the built-in ✕ → all rows reappear
4. Hit Ctrl+F with the main window focused → search box gets focus
5. Toggle the "Show" checkbox on a filtered row → the flame chart updates
   (confirms filter and visibility are independent concerns)
6. Click "Refresh from J-Link" (F5) → search text survives the rebuild

### Feature 2 (zoom to selection)

1. Launch the profiler on the `Trace_Test` app
2. Click the "Zoom to Selection" toolbar button (or Ctrl+R) → cursor becomes
   a crosshair; status bar shows the hint
3. Drag horizontally across part of the flame chart → translucent yellow band
   tracks the selection
4. Release → view zooms to exactly the selected range, window spinbox updates
   to reflect the new width, toolbar button auto-un-toggles
5. Toggle select mode again, start a drag, press Esc → overlay disappears,
   mode exits, original view preserved
6. Confirm normal hover / pick-spans / measurement-cursor interactions work
   unchanged after exiting select mode
7. Switch units us↔ms, enter select mode, drag → verify the window spinbox
   value is correct in the current unit

## Critical files

- [D:/Projects/Profiler/gui/summary_dock.py](D:/Projects/Profiler/gui/summary_dock.py)
- [D:/Projects/Profiler/gui/main_window.py](D:/Projects/Profiler/gui/main_window.py)
