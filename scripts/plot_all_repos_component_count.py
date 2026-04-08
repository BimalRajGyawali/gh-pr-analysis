#!/usr/bin/env python3
"""
Plot distribution of the number of connected components per PR.

Metric:
  connected_component_count = number of connected components with size >= 2
  in the induced changed-symbol call graph.

All PRs are included:
  - If connected_component_count is missing (e.g. malformed row), treat as 0.
  - If n_nodes == 0, upstream effectively yields connected_component_count == 0.

Output:
  viz_output_all_repos/all_repos_pr_component_count_histogram.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gh_pr_analysis.plots.histogram_style import X_AXIS_PAD, axis_hi_and_clip, format_share_pct

DEFAULT_IN = _ROOT / "viz_output_all_repos" / "aggregate_pr_connectivity.json"
DEFAULT_OUT = _ROOT / "viz_output_all_repos" / "all_repos_pr_component_count_histogram.png"
DEFAULT_OUT_DEFINED_ONLY = (
    _ROOT / "viz_output_all_repos" / "all_repos_pr_component_count_histogram_defined_only.png"
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Plot connected_component_count  across all PRs."
    )
    p.add_argument("--stats", type=Path, default=DEFAULT_IN, help="Connectivity JSON path")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output PNG path")
    p.add_argument(
        "--defined-only",
        action="store_true",
        help="Only include PRs with n_nodes>0 (i.e. representable changed-symbol graphs).",
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

    counts: list[int] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if args.defined_only:
            nn = r.get("n_nodes")
            if not isinstance(nn, int) or nn <= 0:
                continue
        v = r.get("connected_component_count")
        counts.append(int(v) if isinstance(v, int) and v >= 0 else 0)

    if not counts:
        raise SystemExit("No PR rows available to plot.")

    n_total = len(counts)
    n_gt0 = sum(1 for c in counts if c > 0)
    thresholds = [1, 2, 3, 5, 10]
    n_ge = {t: sum(1 for c in counts if c >= t) for t in thresholds}

    # Clip tail for readability: show up to p99 + 1 (merged tail).
    x_hi, clipped, merged_tail = axis_hi_and_clip(counts, q=0.99, slop=2)

    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    bins = list(range(0, x_hi + 2))  # integer bins [0..x_hi+1)
    ax.hist(clipped, bins=bins, edgecolor="black", alpha=0.88, color="tab:blue")

    ax.set_xlim(-X_AXIS_PAD, x_hi + X_AXIS_PAD)
    ax.set_xlabel("Number of connected components per PR (size ≥ 2)")
    ax.set_ylabel("Number of PRs")
    ax.set_title(
        "PR vs. Connected Component Count"
        + (" (defined-only: n_nodes>0)" if args.defined_only else "")
    )

    info_lines = [
        f"PRs total: {n_total:,}",
        f"components > 0: {n_gt0:,} ({pct(n_gt0, n_total):.1f}%)",
    ]
    for t in thresholds[1:]:
        info_lines.append(f"components ≥ {t}: {n_ge[t]:,} ({pct(n_ge[t], n_total):.1f}%)")

    if merged_tail:
        info_lines.append(f"Tail merged at {x_hi}+: {format_share_pct(sum(1 for c in counts if c > x_hi), n_total)}")

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

