#!/usr/bin/env python3
"""Plot per-PR median multi-node component size across PRs.

We exclude singletons from the metric by construction:
- For a PR with >=1 multi-node connected component (size >= 2),
  value = median(connected_component_sizes).
- Otherwise (no multi-node components, including n_nodes==0),
  value = 0.

--defined-only drops PRs with n_nodes==0.

Histogram includes 0, so we plot on a linear x-axis.
To keep exact half-integers (median of integer sizes), we histogram in units of
0.5 nodes:
  value2 = int(round(value * 2))
  (0, 1, 2, 3, ...) maps back to value2/2.

Output (default):
  viz_output_all_repos/all_repos_pr_median_component_histogram.png
Output (--defined-only):
  viz_output_all_repos/all_repos_pr_median_component_histogram_defined_only.png
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gh_pr_analysis.plots.histogram_style import X_AXIS_PAD, axis_hi_and_clip, format_share_pct


DEFAULT_IN = _ROOT / "viz_output_all_repos" / "aggregate_pr_connectivity.json"
DEFAULT_OUT = _ROOT / "viz_output_all_repos" / "all_repos_pr_median_component_histogram.png"
DEFAULT_OUT_DEFINED_ONLY = (
    _ROOT / "viz_output_all_repos" / "all_repos_pr_median_component_histogram_defined_only.png"
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Median multi-node component size across PRs.")
    p.add_argument("--stats", type=Path, default=DEFAULT_IN, help="Connectivity JSON path")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output PNG path")
    p.add_argument(
        "--defined-only",
        action="store_true",
        help="Only include PRs with n_nodes>0; drop n_nodes==0 rows.",
    )
    return p


def pct(n: int, d: int) -> float:
    return (100.0 * n / d) if d else 0.0


def median_for_row(r: dict) -> int:
    """Return median size in units of 0.5 nodes (value2)."""
    cc = r.get("connected_component_count")
    connected_sizes = r.get("connected_component_sizes")

    if isinstance(cc, int) and cc > 0 and isinstance(connected_sizes, list) and connected_sizes:
        nums = [s for s in connected_sizes if isinstance(s, (int, float))]
        if nums:
            med = statistics.median(nums)
            # nums are component sizes (integers). median is integer or .5; multiply by 2.
            return int(round(float(med) * 2.0))
    return 0


def main() -> None:
    args = build_parser().parse_args()

    stats = args.stats.resolve()
    out = (
        DEFAULT_OUT_DEFINED_ONLY.resolve()
        if args.defined_only and args.out == DEFAULT_OUT
        else args.out.resolve()
    )

    if not stats.is_file():
        raise SystemExit(f"Stats file not found: {stats}")

    try:
        data = json.loads(stats.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"Could not read {stats}: {e}") from e

    rows = data.get("per_pr")
    if not isinstance(rows, list):
        raise SystemExit(f"Invalid stats file (missing per_pr array): {stats}")

    values2: list[int] = []
    n_nodes_pos = 0

    for r in rows:
        if not isinstance(r, dict):
            continue
        nn = r.get("n_nodes")
        if isinstance(nn, int) and nn > 0:
            n_nodes_pos += 1
        if args.defined_only and not (isinstance(nn, int) and nn > 0):
            continue
        values2.append(median_for_row(r))

    if not values2:
        raise SystemExit("No PR rows available for plotting.")

    n_total = len(values2)
    n_zero = sum(1 for v2 in values2 if v2 == 0)
    nonzero2 = [v2 for v2 in values2 if v2 > 0]
    n_nonzero = len(nonzero2)

    thresholds_nodes = [5, 6, 10, 20]
    thresholds2 = [2 * t for t in thresholds_nodes]
    n_ge = {t: sum(1 for v2 in values2 if v2 >= 2 * t) for t in thresholds_nodes}

    x_hi2, clipped2, merged_tail = axis_hi_and_clip(values2, q=0.99, slop=2)

    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    bins = list(range(0, x_hi2 + 2))
    ax.hist(clipped2, bins=bins, edgecolor="black", alpha=0.88, color="tab:purple")

    ax.set_xlim(-X_AXIS_PAD, x_hi2 + X_AXIS_PAD)
    ax.set_xlabel("Median multi-node component size (nodes; 0 means none)")
    ax.set_ylabel("Number of PRs")
    ax.set_title(
        "Per-PR median multi-node connected component size — all repos"
        + (" (defined-only: n_nodes>0)" if args.defined_only else "")
    )

    # Reference lines.
    for t in thresholds2:
        if t <= x_hi2:
            ax.axvline(t, color="#666666", linestyle="--", linewidth=1.2, alpha=0.7)

    # Tick labels in node units (0.5 increments).
    xticks = list(range(0, x_hi2 + 1, 2))
    ax.set_xticks(xticks)
    ax.set_xticklabels([str(x / 2) for x in xticks])

    median_val = (float(np.median(nonzero2)) / 2.0) if nonzero2 else float("nan")

    info_lines = [
        f"PRs in plot: {n_total:,}",
        f"median: {median_val:.3g}" if nonzero2 else "median: —",
        f"median == 0: {n_zero:,} ({pct(n_zero, n_total):.1f}%)",
    ]
    for t in thresholds_nodes:
        info_lines.append(f"median ≥ {t}: {n_ge[t]:,} ({pct(n_ge[t], n_nonzero):.1f}%)" if n_nonzero else f"median ≥ {t}: {n_ge[t]:,} (—)")

    if merged_tail:
        info_lines.append(
            f"Tail merged at {x_hi2/2:g}+: {format_share_pct(sum(1 for v2 in values2 if v2 > x_hi2), n_total)}"
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
    fig.tight_layout()

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
