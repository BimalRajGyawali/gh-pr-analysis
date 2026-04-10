#!/usr/bin/env python3
"""Plot largest connected component size per PR (among components of size ≥ 2).

Otherwise (including n_nodes==0), value is 0.

Output (single file, two panels: all PRs and n_nodes>0 only):
  viz_output_all_repos/connected_components/all_repos_pr_largest_connected_component_histogram_merged.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gh_pr_analysis.plots.histogram_style import X_AXIS_PAD, axis_hi_and_clip, format_share_pct

_DEFAULT_VIZ = _ROOT / "viz_output_all_repos"
_DEFAULT_CC = _DEFAULT_VIZ / "connected_components"
DEFAULT_IN = _DEFAULT_CC / "aggregate_pr_connectivity.json"
DEFAULT_OUT = _DEFAULT_CC / "all_repos_pr_largest_connected_component_histogram_merged.png"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Largest connected component size across PRs (merged two-panel figure).")
    p.add_argument("--stats", type=Path, default=DEFAULT_IN, help="Connectivity JSON path")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output merged PNG path")
    return p


def pct(n: int, d: int) -> float:
    return (100.0 * n / d) if d else 0.0


def largest_component_values(rows: list, defined_only: bool) -> list[int]:
    values: list[int] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        nn = r.get("n_nodes")
        if defined_only and not (isinstance(nn, int) and nn > 0):
            continue

        cc = r.get("connected_component_count")
        sizes = r.get("connected_component_sizes")

        lm = 0
        if isinstance(cc, int) and cc > 0 and isinstance(sizes, list) and sizes:
            nums = [s for s in sizes if isinstance(s, (int, float))]
            if nums:
                lm = int(max(nums))

        values.append(lm)
    return values


def draw_largest_component_panel(ax, values: list[int], defined_only: bool) -> None:
    if not values:
        ax.set_visible(False)
        return

    n_total = len(values)
    n_zero = sum(1 for v in values if v == 0)
    nonzero = [v for v in values if v > 0]
    n_nonzero = len(nonzero)
    thresholds = [5, 6, 10, 20]
    n_ge = {t: sum(1 for v in values if v >= t) for t in thresholds}

    x_hi, clipped, merged_tail = axis_hi_and_clip(values, q=0.99, slop=2)

    bins = list(range(0, x_hi + 2))
    ax.hist(clipped, bins=bins, edgecolor="black", alpha=0.88, color="tab:green")

    ax.set_xlim(-X_AXIS_PAD, x_hi + X_AXIS_PAD)
    ax.set_xlabel("Largest component (nodes)")
    ax.set_ylabel("Number of PRs")
    ax.set_title(
        "PR vs. largest component"
        + (" (defined-only: n_nodes>0)" if defined_only else "")
    )

    for t in thresholds:
        if t <= x_hi:
            ax.axvline(t, color="#666666", linestyle="--", linewidth=1.2, alpha=0.7)

    info_lines = [
        f"PRs in plot: {n_total:,}",
        f"median: {float(np.median(nonzero)):.3g}" if nonzero else "median: —",
        f"largest == 0: {n_zero:,} ({pct(n_zero, n_total):.1f}%)",
    ]
    for t in thresholds:
        info_lines.append(
            f"largest ≥ {t}: {n_ge[t]:,} ({pct(n_ge[t], n_nonzero):.1f}%)"
            if n_nonzero
            else f"largest ≥ {t}: {n_ge[t]:,} (—)"
        )

    if merged_tail:
        info_lines.append(
            f"Tail merged at {x_hi}+: {format_share_pct(sum(1 for v in values if v > x_hi), n_total)}"
        )

    ax.text(
        0.985,
        0.98,
        "\n".join(info_lines),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.92, "edgecolor": "#cccccc"},
    )

    ax.grid(True, axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def main() -> None:
    args = build_parser().parse_args()

    stats = args.stats.resolve()
    out = args.out.resolve()

    if not stats.is_file():
        raise SystemExit(f"Stats file not found: {stats}")

    try:
        data = json.loads(stats.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"Could not read {stats}: {e}") from e

    rows = data.get("per_pr")
    if not isinstance(rows, list):
        raise SystemExit(f"Invalid stats file (missing per_pr array): {stats}")

    values_all = largest_component_values(rows, False)
    values_def = largest_component_values(rows, True)
    if not values_all or not values_def:
        raise SystemExit("No PR rows available for plotting.")

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(12.5, 12.0))
    draw_largest_component_panel(ax0, values_all, False)
    draw_largest_component_panel(ax1, values_def, True)
    fig.tight_layout()

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
