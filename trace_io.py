"""Trace export: JSON and CSV."""

import csv
import json
from datetime import datetime


def export_json(path, spans, meta=None, marks=None, pause_regions=None, wrapped=False):
    """Write spans, marks, pause regions, and metadata to a JSON file."""
    data = {
        "metadata": dict(meta or {}),
        "spans": spans,
        "marks": list(marks or []),
        "pause_regions": list(pause_regions or []),
    }
    data["metadata"].setdefault("exported_at", datetime.now().isoformat(timespec="seconds"))
    data["metadata"].setdefault("span_count", len(spans))
    data["metadata"].setdefault("mark_count", len(marks or []))
    data["metadata"].setdefault("pause_region_count", len(pause_regions or []))
    data["metadata"]["wrapped"] = bool(wrapped)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def export_csv(path, spans):
    """Write spans as a flat CSV with a header row. Marks are not included."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "addr", "start_us", "end_us", "duration_us", "depth", "ipsr"])
        for sp in spans:
            w.writerow([
                sp["name"],
                f"0x{sp['addr']:08X}",
                f"{sp['start_us']:.3f}",
                f"{sp['end_us']:.3f}",
                f"{sp['duration_us']:.3f}",
                sp["depth"],
                sp.get("ipsr", 0),
            ])


def import_json(path):
    """Load a trace back from a JSON export.

    Returns (spans, marks, pause_regions, metadata). Backward-compatible
    with older exports that didn't include "marks" or "pause_regions".
    """
    with open(path, "r") as f:
        data = json.load(f)
    return (
        data.get("spans", []),
        data.get("marks", []),
        data.get("pause_regions", []),
        data.get("metadata", {}),
    )
