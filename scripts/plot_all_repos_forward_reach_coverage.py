#!/usr/bin/env python3
"""
Plot distribution of FPR from aggregate_pr_connectivity.json.

FPR is the fraction of changed nodes that fall inside at least one root flow of size ≥ 2.

Output:
  viz_output_all_repos/flows/all_repos_pr_fpr_histogram.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_VIZ = _ROOT / "viz_output_all_repos"
_DEFAULT_CC = _DEFAULT_VIZ / "connected_components"
_DEFAULT_FLOWS = _DEFAULT_VIZ / "flows"
DEFAULT_IN = _DEFAULT_CC / "aggregate_pr_connectivity.json"
DEFAULT_OUT = _DEFAULT_FLOWS / "all_repos_pr_fpr_histogram.png"
DEFAULT_OUT_DEFINED_ONLY = _DEFAULT_FLOWS / "all_repos_pr_fpr_histogram_defined_only.png"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Plot FPR across PRs.")
    p.add_argument("--stats", type=Path, default=DEFAULT_IN, help="Connectivity JSON path")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output PNG path")
    p.add_argument(
        "--defined-only",
        action="store_true",
        help="Only include PRs with n_nodes>0.",
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

    values: list[float] = []
    n_total = len(rows)
    n_nodes_pos = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        nn = r.get("n_nodes")
        if isinstance(nn, int) and nn > 0:
            n_nodes_pos += 1
        cov = r.get("forward_reach_coverage")
        if args.defined_only:
            if not (isinstance(nn, int) and nn > 0):
                continue
            values.append(float(cov) if isinstance(cov, (int, float)) else 0.0)
        else:
            if isinstance(nn, int) and nn <= 0:
                values.append(0.0)
            else:
                values.append(float(cov) if isinstance(cov, (int, float)) else 0.0)

    if not values:
        raise SystemExit("No PR rows available to plot.")

    n_total_effective = len(values)

    n_gt0 = sum(1 for x in values if x > 0.0)
    n_ge50 = sum(1 for x in values if x >= 0.5)
    n_ge80 = sum(1 for x in values if x >= 0.8)

    bin_edges = [i / 20 for i in range(21)]
    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    ax.hist(values, bins=bin_edges, edgecolor="black", alpha=0.88, color="tab:blue")

    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("FPR")
    ax.set_ylabel("Number of PRs")
    title_suffix = " (defined-only: n_nodes>0)" if args.defined_only else ""
    ax.set_title(
        f"PR vs. FPR{title_suffix}\n"
        "(share of changed nodes covered by flows of size ≥ 2)"
    )

    for x, color in ((0.5, "tab:orange"), (0.8, "tab:red")):
        ax.axvline(x, color=color, linestyle="--", linewidth=1.5, alpha=0.9)

    if args.defined_only:
        info = (
            f"PRs total: {n_total:,}\n"
            f"PRs with n_nodes>0: {n_nodes_pos:,} ({pct(n_nodes_pos, n_total):.1f}%)\n"
            f"Plotted: {len(values):,}\n"
            f"FPR > 0: {n_gt0:,} ({pct(n_gt0, n_total_effective):.1f}%)\n"
            f"FPR >= 0.5: {n_ge50:,} ({pct(n_ge50, n_total_effective):.1f}%)\n"
            f"FPR >= 0.8: {n_ge80:,} ({pct(n_ge80, n_total_effective):.1f}%)"
        )
    else:
        info = (
            f"PRs total: {n_total:,}\n"
            f"n_nodes==0 plotted as 0: {sum(1 for r in rows if isinstance(r, dict) and r.get('n_nodes') == 0):,}\n"
            f"FPR > 0: {n_gt0:,} ({pct(n_gt0, n_total_effective):.1f}%)\n"
            f"FPR >= 0.5: {n_ge50:,} ({pct(n_ge50, n_total_effective):.1f}%)\n"
            f"FPR >= 0.8: {n_ge80:,} ({pct(n_ge80, n_total_effective):.1f}%)"
        )
    ax.text(
        0.985,
        0.98,
        info,
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
