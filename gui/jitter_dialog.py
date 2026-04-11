"""Period / jitter analysis dialog.

Modal QDialog that, given a name and a list of event timestamps in
microseconds, computes inter-arrival statistics and shows:

  - A stats label (count, mean period, stddev, min, max, jitter, frequency)
  - A histogram of period distribution (~20 bins)
  - A time-series plot of period vs invocation index

Used by both the Function Summary dock (right-click → Analyze Period /
Jitter) and the Markers dock.
"""

import math

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .theme import THEME, configure_pyqtgraph


class JitterDialog(QtWidgets.QDialog):
    def __init__(self, name, times_us, unit_label, unit_scale, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Period / Jitter: {name}")
        self.resize(820, 640)

        # Compute periods (inter-arrival deltas) in microseconds
        sorted_times = sorted(times_us)
        periods_us = [
            sorted_times[i + 1] - sorted_times[i]
            for i in range(len(sorted_times) - 1)
        ]

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        if len(periods_us) == 0:
            label = QtWidgets.QLabel(
                f"<b>{name}</b><br><br>"
                "Need at least 2 events to compute periods. "
                "(This name has only 1 occurrence.)"
            )
            label.setWordWrap(True)
            layout.addWidget(label)
            close_btn = QtWidgets.QPushButton("Close")
            close_btn.clicked.connect(self.accept)
            layout.addWidget(close_btn, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
            return

        n = len(periods_us)
        mean_us = sum(periods_us) / n
        variance = sum((p - mean_us) ** 2 for p in periods_us) / n
        stddev_us = math.sqrt(variance)
        min_us = min(periods_us)
        max_us = max(periods_us)
        jitter_us = max_us - min_us
        freq_hz = 1_000_000.0 / mean_us if mean_us > 0 else 0.0

        # Stats label — display in current unit
        u = unit_label
        s = unit_scale
        stats_html = (
            f"<table cellspacing='0' cellpadding='4' style='font-family:Segoe UI,sans-serif'>"
            f"<tr><td><b>Function/Marker:</b></td><td>{name}</td></tr>"
            f"<tr><td><b>Periods analyzed:</b></td><td>{n}</td></tr>"
            f"<tr><td><b>Mean period:</b></td><td>{mean_us * s:.4f} {u}</td></tr>"
            f"<tr><td><b>Std dev:</b></td><td>{stddev_us * s:.4f} {u}</td></tr>"
            f"<tr><td><b>Min:</b></td><td>{min_us * s:.4f} {u}</td></tr>"
            f"<tr><td><b>Max:</b></td><td>{max_us * s:.4f} {u}</td></tr>"
            f"<tr><td><b>Jitter (max - min):</b></td><td>{jitter_us * s:.4f} {u}</td></tr>"
            f"<tr><td><b>Frequency (1/mean):</b></td><td>{freq_hz:.2f} Hz</td></tr>"
            f"</table>"
        )
        stats_label = QtWidgets.QLabel(stats_html)
        stats_label.setStyleSheet(
            f"background:{THEME['bg_raised']}; color:{THEME['text_primary']};"
            "padding:8px; border-radius:4px;"
        )
        layout.addWidget(stats_label)

        # Histogram — pyqtgraph colors are configured once at app startup
        # by configure_pyqtgraph(); we call it here as a safety net in case
        # this dialog is opened before the main window initializes.
        configure_pyqtgraph()
        pg.setConfigOptions(antialias=False)

        hist_label = QtWidgets.QLabel("<b>Period distribution (histogram)</b>")
        layout.addWidget(hist_label)

        hist_plot = pg.PlotWidget()
        hist_plot.setLabel("bottom", f"Period ({u})")
        hist_plot.setLabel("left", "Count")
        hist_plot.showGrid(x=True, y=True, alpha=0.25)
        hist_plot.getViewBox().setMenuEnabled(False)

        n_bins = min(30, max(5, len(periods_us) // 3 or 5))
        if max_us > min_us:
            bin_w = (max_us - min_us) / n_bins
            bin_edges = [min_us + i * bin_w for i in range(n_bins + 1)]
        else:
            bin_edges = [min_us, min_us + 1.0]
            n_bins = 1
            bin_w = 1.0

        bin_counts = [0] * n_bins
        for p in periods_us:
            idx = int((p - bin_edges[0]) / bin_w)
            if idx >= n_bins:
                idx = n_bins - 1
            if idx < 0:
                idx = 0
            bin_counts[idx] += 1

        bar_x = [(bin_edges[i] + bin_edges[i + 1]) / 2 * s for i in range(n_bins)]
        bar = pg.BarGraphItem(
            x=bar_x,
            height=bin_counts,
            width=bin_w * s * 0.9,
            brush="#4C78A8",
            pen=pg.mkPen("#7a9bbf"),
        )
        hist_plot.addItem(bar)
        layout.addWidget(hist_plot, 1)

        # Time-series: period vs invocation index
        ts_label = QtWidgets.QLabel("<b>Period vs invocation index</b>")
        layout.addWidget(ts_label)

        ts_plot = pg.PlotWidget()
        ts_plot.setLabel("bottom", "Invocation #")
        ts_plot.setLabel("left", f"Period ({u})")
        ts_plot.showGrid(x=True, y=True, alpha=0.25)
        ts_plot.getViewBox().setMenuEnabled(False)

        xs = list(range(1, n + 1))
        ys = [p * s for p in periods_us]
        ts_plot.plot(xs, ys, pen=pg.mkPen("#F58518", width=2), symbol="o", symbolSize=4,
                     symbolBrush="#F58518")
        # Mean line for reference
        mean_line = pg.InfiniteLine(
            pos=mean_us * s, angle=0,
            pen=pg.mkPen("#54A24B", width=1, style=QtCore.Qt.PenStyle.DashLine),
            label=f"mean = {mean_us * s:.3f} {u}",
            labelOpts={"position": 0.95, "color": "#54A24B"},
        )
        ts_plot.addItem(mean_line)
        layout.addWidget(ts_plot, 1)

        # Close button
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
