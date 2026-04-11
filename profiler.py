"""
Cortex-M Function Profiler — main CLI entry point.

Reads a trace buffer from a target via J-Link, resolves function names from
an ELF file, matches enter/exit pairs into spans, and displays an interactive
flame-chart GUI (PySide6 + pyqtgraph).

Usage:
    python profiler.py <elf_file> [options]

Example:
    python profiler.py ../QS127S_2/FW-APP-QS127S-audio/app/Trace_Test/build/executable.elf
    python profiler.py executable.elf --cpu-mhz 192 --device AMA4B2KP-KBR
    python profiler.py executable.elf --load trace.json        # load an exported trace

Navigation:
    - Mouse wheel / scrollbar → horizontal pan
    - View menu → units, color mode, measurement cursors
    - Toolbar → window size, jump-to-time, find function, refresh
"""

import argparse
import os
import sys

from trace_reader import (
    TRACE_BUFFER_SIZE,
    connect_jlink,
    load_elf_symbols,
    read_trace,
)
from span_builder import (
    build_spans,
    parse_events,
    print_summary,
    resolve_names,
)
from trace_io import import_json
from gui import show_gui


def main():
    parser = argparse.ArgumentParser(
        description="Cortex-M Function Profiler — J-Link trace buffer → interactive flame chart"
    )
    parser.add_argument(
        "elf",
        nargs="?",
        default=None,
        help="ELF file with trace_buf/trace_idx symbols. "
             "Optional when using --load or opening a trace via the GUI.",
    )
    parser.add_argument("--device", default="AMA4B2KP-KBR", help="J-Link target device (default: AMA4B2KP-KBR)")
    parser.add_argument("--cpu-mhz", type=float, default=96.0, help="CPU clock frequency in MHz (default: 96)")
    parser.add_argument("--no-plot", action="store_true", help="Print summary only, skip the GUI")
    parser.add_argument("--load", help="Load spans from a previously exported JSON file instead of J-Link")

    args = parser.parse_args()

    # No ELF and no --load: open empty GUI so user can use
    # File → Open Trace (Ctrl+O) or File → Connect to J-Link (Ctrl+J).
    if args.elf is None and not args.load:
        show_gui([], cpu_mhz=args.cpu_mhz)
        return

    # Offline mode: load from a JSON file instead of connecting to J-Link
    if args.load:
        print(f"Loading spans from: {args.load}")
        spans, marks, pause_regions, meta = import_json(args.load)
        wrapped = bool(meta.get("wrapped", False))
        print(
            f"  Loaded {len(spans)} spans, {len(marks)} marks, "
            f"{len(pause_regions)} pause regions ({meta.get('exported_at', '?')})"
        )
        print_summary(spans)
        if not args.no_plot:
            show_gui(
                spans,
                marks=marks,
                pause_regions=pause_regions,
                wrapped=wrapped,
                elf_path=args.elf,
                cpu_mhz=args.cpu_mhz,
            )
        return

    # Live mode: connect to J-Link
    print(f"Loading symbols from: {args.elf}")
    name_to_addr, addr_to_name = load_elf_symbols(args.elf)
    print(f"  Found {len(name_to_addr)} symbols")

    print(f"Connecting to {args.device} via J-Link...")
    jlink = connect_jlink(args.device)

    def read_and_parse():
        """Refresh closure — reads the trace buffer fresh and builds spans+marks+pauses."""
        raw_buf, trace_idx = read_trace(jlink, name_to_addr)
        n_events = min(trace_idx, TRACE_BUFFER_SIZE)
        wrapped = trace_idx > TRACE_BUFFER_SIZE
        print(f"  trace_idx = {trace_idx} ({n_events} events{', wrapped' if wrapped else ''})")
        if n_events == 0:
            return [], [], [], wrapped
        events = parse_events(raw_buf, trace_idx)
        resolve_names(events, addr_to_name, elf_path=args.elf)
        spans, marks, pause_regions = build_spans(events, args.cpu_mhz)
        return spans, marks, pause_regions, wrapped

    try:
        spans, marks, pause_regions, wrapped = read_and_parse()
        if not spans and not marks:
            print("No trace events recorded.")
            return

        print(
            f"  Matched {len(spans)} function call spans, "
            f"{len(marks)} marks, {len(pause_regions)} pause regions"
        )
        if pause_regions:
            for i, r in enumerate(pause_regions[:5]):
                dur_us = r["end_us"] - r["start_us"]
                print(f"    pause #{i + 1}: {r['start_us']:.2f} - {r['end_us']:.2f} us ({dur_us:.2f} us)")
            if len(pause_regions) > 5:
                print(f"    ... and {len(pause_regions) - 5} more")
        print_summary(spans)

        if not args.no_plot:
            show_gui(
                spans,
                marks=marks,
                pause_regions=pause_regions,
                wrapped=wrapped,
                refresh_fn=read_and_parse,
                elf_path=args.elf,
                cpu_mhz=args.cpu_mhz,
            )
    finally:
        try:
            jlink.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
