"""Parse raw trace events into time spans, resolve symbol names."""

import struct
import subprocess
from collections import defaultdict

from trace_reader import (
    TRACE_BUFFER_SIZE,
    TRACE_EVENT_SIZE,
    EVENT_FMT,
    read_elf_string,
)


# ── Demangling ───────────────────────────────────────────────────────

def demangle(name):
    """Demangle a C++ symbol via arm-none-eabi-c++filt. Falls back to raw name."""
    if not name.startswith("_Z"):
        return name
    try:
        result = subprocess.run(
            ["arm-none-eabi-c++filt", name],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return name


# ── Event parsing ────────────────────────────────────────────────────

def parse_events(raw_buf, trace_idx):
    """Decode the circular buffer into an ordered list of raw events."""
    n_events = min(trace_idx, TRACE_BUFFER_SIZE)
    start = trace_idx % TRACE_BUFFER_SIZE if trace_idx > TRACE_BUFFER_SIZE else 0

    events = []
    for i in range(n_events):
        buf_i = (start + i) % TRACE_BUFFER_SIZE
        offset = buf_i * TRACE_EVENT_SIZE
        etype, ipsr, cyccnt, context = struct.unpack_from(EVENT_FMT, raw_buf, offset)
        events.append({
            "type": etype,
            "ipsr": ipsr,
            "cyccnt": cyccnt,
            "addr": context,
        })
    return events


def resolve_names(events, addr_to_name, elf_path=None):
    """Attach human-readable names to each event.

    For enter/exit events (type 0/1), resolve via the ELF symbol table and
    demangle. For mark events (type 2), resolve the pointer to a string
    literal by reading the ELF's .rodata/.text sections.
    """
    fn_cache = {}
    str_cache = {}
    for ev in events:
        addr = ev["addr"]
        if ev["type"] == 2:
            if addr not in str_cache:
                str_cache[addr] = read_elf_string(elf_path, addr) if elf_path else f"<0x{addr:08X}>"
            ev["name"] = str_cache[addr]
        else:
            raw = (
                addr_to_name.get(addr)
                or addr_to_name.get(addr & ~1)
                or f"0x{addr:08X}"
            )
            if raw not in fn_cache:
                fn_cache[raw] = demangle(raw)
            ev["name"] = fn_cache[raw]


def _build_spans_for_stream(events, cpu_mhz):
    """Build spans from a single call-stack stream (thread or merged-ISR)."""
    spans = []
    stack = []
    for ev in events:
        if ev["type"] == 0:  # enter
            stack.append(ev)
        elif ev["type"] == 1:  # exit
            for i in range(len(stack) - 1, -1, -1):
                if stack[i]["addr"] == ev["addr"]:
                    enter = stack.pop(i)
                    dt = ev["cyccnt"] - enter["cyccnt"]
                    if dt < 0:
                        dt += 0x1_0000_0000
                    spans.append({
                        "name": enter["name"],
                        "addr": enter["addr"],
                        "start_us": enter["cyccnt"] / cpu_mhz,
                        "end_us": ev["cyccnt"] / cpu_mhz,
                        "duration_us": dt / cpu_mhz,
                        "depth": i,
                        "ipsr": enter.get("ipsr", 0),
                    })
                    break
    return spans


_PAUSE_SENTINEL = "__trace_pause__"
_RESUME_SENTINEL = "__trace_resume__"


def build_spans(events, cpu_mhz):
    """Parse events into (spans, marks, pause_regions).

    Thread and ISR streams are matched independently so preemption doesn't
    mis-pair enter/exit events. Marks (type 2) are extracted separately.
    The two sentinel marks emitted by `trace_pause()` / `trace_resume()`
    are stripped from the visible mark list and converted into pause-region
    pairs `{start_us, end_us}` for the profiler to render as gray bands.
    """
    raw_marks = []
    thread_events = []
    isr_events = []

    for ev in events:
        if ev["type"] == 2:
            raw_marks.append({
                "name": ev.get("name", f"<0x{ev['addr']:08X}>"),
                "t_us": ev["cyccnt"] / cpu_mhz,
                "ipsr": ev.get("ipsr", 0),
            })
        elif ev.get("ipsr", 0) == 0:
            thread_events.append(ev)
        else:
            isr_events.append(ev)

    spans = (
        _build_spans_for_stream(thread_events, cpu_mhz)
        + _build_spans_for_stream(isr_events, cpu_mhz)
    )

    # Sort marks chronologically before pairing (events list isn't strictly
    # ordered when streams are mixed in time)
    raw_marks.sort(key=lambda m: m["t_us"])

    pause_regions, marks = _extract_pause_regions(raw_marks)
    return spans, marks, pause_regions


def _extract_pause_regions(marks):
    """Pair `__trace_pause__` / `__trace_resume__` sentinels into regions.

    Returns (regions, filtered_marks) where regions is a list of
    {start_us, end_us} dicts and filtered_marks excludes the sentinels.

    A pause without a matching resume (e.g. trace ended mid-pause) extends
    to the time of the last regular event.
    """
    regions = []
    filtered = []
    open_pause_t = None  # set when we've seen a pause with no matching resume yet
    for m in marks:
        if m["name"] == _PAUSE_SENTINEL:
            if open_pause_t is None:
                open_pause_t = m["t_us"]
            # nested pauses just keep the outer start (idempotent)
            continue
        if m["name"] == _RESUME_SENTINEL:
            if open_pause_t is not None:
                regions.append({"start_us": open_pause_t, "end_us": m["t_us"]})
                open_pause_t = None
            continue
        filtered.append(m)

    # Open pause at end of trace: extend to last known timestamp
    if open_pause_t is not None:
        last_t = filtered[-1]["t_us"] if filtered else open_pause_t
        regions.append({"start_us": open_pause_t, "end_us": max(last_t, open_pause_t)})

    return regions, filtered


# ── Call tree (hierarchical aggregation) ─────────────────────────────

def build_call_tree(spans):
    """Build an aggregated call tree from a flat span list.

    Walks spans in start-time order using a stack to establish parent-child
    relationships. Children at the same call-site are aggregated by function
    name, so `foo` called 5 times from `main` appears as one `foo` node with
    count=5 and summed inclusive/exclusive times.

    Returns a root node dict:
        {
            "name": "<root>",
            "count": 0,
            "inclusive_us": 0.0,
            "exclusive_us": 0.0,
            "children": {name: node, ...},
        }
    """
    root = {
        "name": "<root>",
        "count": 0,
        "inclusive_us": 0.0,
        "exclusive_us": 0.0,
        "children": {},
    }
    if not spans:
        return root

    spans_sorted = sorted(spans, key=lambda s: s["start_us"])

    # First pass: compute each span's exclusive time
    # (= duration minus sum of directly-contained child durations).
    # Only count a span as a child of the open span when both share the same
    # ipsr context — an ISR preempts a thread function, it does not call it,
    # so the ISR's duration must not be deducted from the thread's exclusive time.
    children_total = [0.0] * len(spans_sorted)

    open_stacks_excl: dict = {}   # ipsr → list of span indices
    for i, sp in enumerate(spans_sorted):
        ipsr = sp.get("ipsr", 0)
        stk = open_stacks_excl.setdefault(ipsr, [])
        while stk and spans_sorted[stk[-1]]["end_us"] <= sp["start_us"]:
            stk.pop()
        if stk:
            children_total[stk[-1]] += sp["duration_us"]
        stk.append(i)

    # Second pass: build the aggregated tree.
    # Use one node-stack per ipsr context so ISR spans never inherit a thread
    # function as their parent (and vice-versa).  Each context's stack is
    # independent and starts from the shared root node.
    node_stacks: dict = {}   # ipsr → list of (end_us, tree_node)
    for i, sp in enumerate(spans_sorted):
        ipsr = sp.get("ipsr", 0)
        stk = node_stacks.setdefault(ipsr, [(float("inf"), root)])
        while len(stk) > 1 and stk[-1][0] <= sp["start_us"]:
            stk.pop()

        _, parent_node = stk[-1]
        name = sp["name"]
        node = parent_node["children"].get(name)
        if node is None:
            node = {
                "name": name,
                "count": 0,
                "inclusive_us": 0.0,
                "exclusive_us": 0.0,
                "children": {},
            }
            parent_node["children"][name] = node

        node["count"] += 1
        node["inclusive_us"] += sp["duration_us"]
        node["exclusive_us"] += sp["duration_us"] - children_total[i]

        stk.append((sp["end_us"], node))

    return root


# ── Summary stats ────────────────────────────────────────────────────

def compute_stats(spans):
    """Per-function call-count, total/avg/min/max duration."""
    stats = defaultdict(lambda: {"count": 0, "total_us": 0.0, "min_us": float("inf"), "max_us": 0.0})
    for sp in spans:
        s = stats[sp["name"]]
        s["count"] += 1
        s["total_us"] += sp["duration_us"]
        s["min_us"] = min(s["min_us"], sp["duration_us"])
        s["max_us"] = max(s["max_us"], sp["duration_us"])
    return stats


def print_summary(spans):
    stats = compute_stats(spans)
    print(f"\n{'Function':<50s} {'Calls':>6s} {'Total(us)':>12s} {'Avg(us)':>10s} {'Min(us)':>10s} {'Max(us)':>10s}")
    print("-" * 100)
    for name in sorted(stats, key=lambda n: stats[n]["total_us"], reverse=True):
        s = stats[name]
        avg = s["total_us"] / s["count"]
        print(f"{name:<50s} {s['count']:>6d} {s['total_us']:>12.2f} {avg:>10.2f} {s['min_us']:>10.2f} {s['max_us']:>10.2f}")
    print()
