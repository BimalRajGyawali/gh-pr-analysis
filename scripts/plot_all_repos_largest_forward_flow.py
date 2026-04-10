#!/usr/bin/env python3
"""Plot largest root flow size per PR (among flows of size ≥ 2).

If a PR has no such flow (including n_nodes==0), value is 0.

Output (default):
  viz_output_all_repos/flows/all_repos_pr_largest_flow_histogram.png
Output (--defined-only):
  viz_output_all_repos/flows/all_repos_pr_largest_flow_histogram_defined_only.png
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
_DEFAULT_FLOWS = _DEFAULT_VIZ / "flows"
DEFAULT_IN = _DEFAULT_CC / "aggregate_pr_connectivity.json"
DEFAULT_OUT = _DEFAULT_FLOWS / "all_repos_pr_largest_flow_histogram.png"
DEFAULT_OUT_DEFINED_ONLY = _DEFAULT_FLOWS / "all_repos_pr_largest_flow_histogram_defined_only.png"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Largest root flow size across PRs.")
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

    values: list[int] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        nn = r.get("n_nodes")
        if args.defined_only and not (isinstance(nn, int) and nn > 0):
            continue

        fc = r.get("forward_flow_count_ge2")
        sizes = r.get("forward_multinode_closure_sizes")

        lm = 0
        if isinstance(fc, int) and fc > 0 and isinstance(sizes, list) and sizes:
            nums = [s for s in sizes if isinstance(s, (int, float))]
            if nums:
                lm = int(max(nums))

        values.append(lm)

    if not values:
        raise SystemExit("No PR rows available for plotting.")

    n_total = len(values)
    n_zero = sum(1 for v in values if v == 0)
    nonzero = [v for v in values if v > 0]
    n_nonzero = len(nonzero)
    thresholds = [5, 6, 10, 20]
    n_ge = {t: sum(1 for v in values if v >= t) for t in thresholds}

    x_hi, clipped, merged_tail = axis_hi_and_clip(values, q=0.99, slop=2)

    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    bins = list(range(0, x_hi + 2))
    ax.hist(clipped, bins=bins, edgecolor="black", alpha=0.88, color="tab:green")

    ax.set_xlim(-X_AXIS_PAD, x_hi + X_AXIS_PAD)
    ax.set_xlabel("Largest flow (nodes)")
    ax.set_ylabel("Number of PRs")
    ax.set_title(
        "PR vs. largest flow"
        + (" (defined-only: n_nodes>0)" if args.defined_only else "")
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
    fig.tight_layout()

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
