"""Trace export: JSON and CSV."""

import csv
import json
import os
import zipfile
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


def export_sltrace(path, spans, meta=None, marks=None, pause_regions=None,
                   wrapped=False, elf_path=None):
    """Write spans + optional ELF to a .sltrace ZIP bundle."""
    elf_name = os.path.basename(elf_path) if elf_path else None
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
    data["metadata"]["elf_path"] = elf_name or ""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("trace.json", json.dumps(data, indent=2))
        if elf_path and os.path.isfile(elf_path) and elf_name:
            zf.write(elf_path, elf_name)


def import_sltrace(path):
    """Load a .sltrace bundle.

    Returns (spans, marks, pause_regions, meta, elf_bytes, elf_name).
    elf_bytes and elf_name are None when the bundle contains no ELF.
    """
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open("trace.json") as f:
            data = json.load(f)
        meta = data.get("metadata", {})
        elf_name = meta.get("elf_path") or None
        elf_bytes = zf.read(elf_name) if elf_name and elf_name in zf.namelist() else None
    return (
        data.get("spans", []),
        data.get("marks", []),
        data.get("pause_regions", []),
        meta,
        elf_bytes,
        elf_name,
    )


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


def validate_trace(data: dict) -> list:
    """Validate a loaded trace dict.  Returns a list of human-readable strings.

    Fatal issues (empty list means the trace is structurally valid).
    Non-fatal issues are prefixed with ``"Warning: "``.  Fatal issues
    have no prefix — callers should refuse to load when any fatal issue
    is present.
    """
    if not isinstance(data, dict):
        return ["File does not contain a JSON object at the top level."]

    spans = data.get("spans")
    if spans is None:
        return ['Missing required key "spans".']
    if not isinstance(spans, list):
        return ['"spans" must be a JSON array.']

    _REQUIRED: dict = {
        "name":        str,
        "start_us":    (int, float),
        "end_us":      (int, float),
        "duration_us": (int, float),
        "depth":       int,
    }

    errors: list = []
    bad = 0
    for i, sp in enumerate(spans):
        if not isinstance(sp, dict):
            bad += 1
            if bad <= 3:
                errors.append(f"spans[{i}] is not an object.")
            continue
        for field, types in _REQUIRED.items():
            if field not in sp:
                bad += 1
                if bad <= 3:
                    errors.append(f'spans[{i}] missing required field "{field}".')
                break
            if not isinstance(sp[field], types):
                bad += 1
                if bad <= 3:
                    expected = types.__name__ if isinstance(types, type) else "/".join(t.__name__ for t in types)
                    errors.append(
                        f"spans[{i}].{field}: expected {expected}, "
                        f"got {type(sp[field]).__name__}."
                    )
                break

    if bad > 3:
        errors.append(f"… and {bad - 3} more malformed span(s).")

    marks = data.get("marks")
    if marks is not None and not isinstance(marks, list):
        errors.append('Warning: "marks" is present but not a JSON array — ignored.')

    pause_regions = data.get("pause_regions")
    if pause_regions is not None and not isinstance(pause_regions, list):
        errors.append('Warning: "pause_regions" is present but not a JSON array — ignored.')

    return errors
