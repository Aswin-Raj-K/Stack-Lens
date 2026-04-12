"""Custom pyqtgraph axis items for the profiler flame chart."""

import pyqtgraph as pg

from .constants import ROW_HEIGHT


class UnitAxis(pg.AxisItem):
    """X-axis that scales tick labels by a unit factor (µs ↔ ms)."""

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
