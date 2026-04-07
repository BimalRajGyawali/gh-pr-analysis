"""Shared integer histogram styling (bar labels, percentile x-cap)."""

from __future__ import annotations

import math
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

X_AXIS_PAD = 0.5


def axis_hi_and_clip(values: list[int], q: float, slop: int) -> tuple[int, list[int], bool]:
    """Return (hi, clipped_series, merged_tail)."""
    n = len(values)
    if n == 0:
        return 0, [], False
    sc = sorted(values)
    m = sc[-1]
    if m <= 0:
        return 0, list(values), False
    idx = min(n - 1, max(0, math.ceil(q * n) - 1))
    p_q = sc[idx]
    if m <= p_q + slop:
        return m, list(values), False
    hi = p_q + 1
    clipped = [min(c, hi) for c in values]
    return hi, clipped, hi < m


def format_share_pct(count: int, n_total: int) -> str:
    if n_total <= 0:
        return "—"
    pct = 100.0 * count / n_total
    if pct >= 10:
        return f"{pct:.0f}%"
    if pct >= 1:
        return f"{pct:.1f}%"
    if pct >= 0.01:
        return f"{pct:.2f}%"
    return "<0.01%"


def bar_label_count_and_pct(count: int, n_total: int) -> str:
    c = int(count)
    if n_total <= 0:
        return f"{c:,}"
    return f"{c:,}\n({format_share_pct(c, n_total)})"


def annotate_histogram_bars(
    ax: plt.Axes,
    patches: Any,
    heights: Any,
    n_total: int,
    hi: int,
) -> float:
    y_max = float(heights.max()) if len(heights) else 0.0
    if y_max <= 0:
        return 0.0

    n_nonempty = sum(1 for h in heights if float(h) > 0)
    min_h = max(1.0, y_max * 0.025)
    if hi > 35 or n_nonempty > 22:
        min_h = max(min_h, y_max * 0.05, 5.0)

    headroom = 1.14
    if n_nonempty > 14:
        headroom += min(0.12, (n_nonempty - 14) * 0.008)
    if hi > 55:
        headroom += 0.06

    # Label strategy:
    # - big bars: two-line label inside the bar (count + percent)
    # - small bars: show a compact label above the bar (count only) so it remains readable
    inside_min_h = max(min_h, y_max * 0.07, 9.0)
    above_min_h = max(1.0, y_max * 0.02, 2.0)

    for patch, h in zip(patches, heights):
        h = float(h)
        if h <= 0:
            continue
        x = patch.get_x() + patch.get_width() / 2.0
        c = int(h)

        if h >= inside_min_h:
            ax.annotate(
                bar_label_count_and_pct(c, n_total),
                xy=(x, h),
                xytext=(0, 2),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8.0,
                color="black",
            )
        elif h >= above_min_h:
            ax.annotate(
                bar_label_count_and_pct(c, n_total),
                xy=(x, h),
                xytext=(0, 2),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=7.8,
                color="black",
            )

    return y_max * headroom


def apply_histogram_x_axis(ax: plt.Axes, hi: int, merged_tail: bool, xlabel_core: str) -> None:
    ax.set_xlim(-X_AXIS_PAD, hi + X_AXIS_PAD)
    # Integer counts on x, but tick spacing scales with range (not a tick per bin).
    ax.xaxis.set_major_locator(
        MaxNLocator(nbins=11, integer=True, min_n_ticks=4)
    )
    xlabel = xlabel_core
    if merged_tail:
        xlabel += f" — last bin is ≥{hi}"
    ax.set_xlabel(xlabel)
    ax.tick_params(axis="x", labelsize=9)
