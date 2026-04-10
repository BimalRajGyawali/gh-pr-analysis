#!/usr/bin/env python3
"""
Plot distribution of CPR from aggregate JSON.

CPR = nodes in connected components of size ≥2, divided by all changed nodes.

Output (single file, two panels: all PRs and n_nodes>0 only):
  viz_output_all_repos/connected_components/all_repos_pr_cpr_histogram_merged.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_VIZ = _ROOT / "viz_output_all_repos"
_DEFAULT_CC = _DEFAULT_VIZ / "connected_components"
DEFAULT_IN = _DEFAULT_CC / "aggregate_pr_connectivity.json"
DEFAULT_OUT = _DEFAULT_CC / "all_repos_pr_cpr_histogram_merged.png"


def cpr_for_row(r: dict) -> float | None:
    v = r.get("cpr")
    if isinstance(v, (int, float)):
        return float(v)
    v = r.get("connected_component_participation")
    if isinstance(v, (int, float)):
        return float(v)
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Plot CPR across PRs (merged two-panel figure).")
    p.add_argument("--stats", type=Path, default=DEFAULT_IN, help="Connectivity JSON path")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output merged PNG path")
    return p


def pct(n: int, d: int) -> float:
    return (100.0 * n / d) if d else 0.0


def cpr_values(rows: list, defined_only: bool) -> list[float]:
    values: list[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        nn = r.get("n_nodes")
        cv = cpr_for_row(r)
        if defined_only:
            if not (isinstance(nn, int) and nn > 0):
                continue
            values.append(cv if cv is not None else 0.0)
        else:
            if isinstance(nn, int) and nn <= 0:
                values.append(0.0)
            else:
                values.append(cv if cv is not None else 0.0)
    return values


def draw_cpr_panel(
    ax,
    rows: list,
    values: list[float],
    defined_only: bool,
    n_total: int,
    n_nodes_pos: int,
) -> None:
    if not values:
        ax.set_visible(False)
        return

    n_total_effective = len(values)
    n_gt0 = sum(1 for x in values if x > 0.0)
    n_ge50 = sum(1 for x in values if x >= 0.5)
    n_ge80 = sum(1 for x in values if x >= 0.8)

    bin_edges = [i / 20 for i in range(21)]
    ax.hist(values, bins=bin_edges, edgecolor="black", alpha=0.88, color="tab:blue")

    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("CPR")
    ax.set_ylabel("Number of PRs")
    title_suffix = " (defined-only: n_nodes>0)" if defined_only else ""
    ax.set_title(
        f"PR vs. CPR{title_suffix}\n"
        "(nodes in components of size ≥2 / changed nodes)"
    )

    for x, color in ((0.5, "tab:orange"), (0.8, "tab:red")):
        ax.axvline(x, color=color, linestyle="--", linewidth=1.5, alpha=0.9)

    if defined_only:
        info = (
            "CPR = nodes in components of size ≥2 / changed nodes\n"
            f"PRs total: {n_total:,}\n"
            f"PRs with n_nodes>0: {n_nodes_pos:,} ({pct(n_nodes_pos, n_total):.1f}%)\n"
            f"Plotted: {len(values):,}\n"
            f"CPR > 0: {n_gt0:,} ({pct(n_gt0, n_total_effective):.1f}%)\n"
            f"CPR >= 0.5: {n_ge50:,} ({pct(n_ge50, n_total_effective):.1f}%)\n"
            f"CPR >= 0.8: {n_ge80:,} ({pct(n_ge80, n_total_effective):.1f}%)"
        )
    else:
        info = (
            "CPR = nodes in components of size ≥2 / changed nodes\n"
            f"PRs total: {n_total:,}\n"
            f"n_nodes==0 plotted as 0: {sum(1 for r in rows if isinstance(r, dict) and r.get('n_nodes') == 0):,}\n"
            f"CPR > 0: {n_gt0:,} ({pct(n_gt0, n_total_effective):.1f}%)\n"
            f"CPR >= 0.5: {n_ge50:,} ({pct(n_ge50, n_total_effective):.1f}%)\n"
            f"CPR >= 0.8: {n_ge80:,} ({pct(n_ge80, n_total_effective):.1f}%)"
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

    n_total = len(rows)
    n_nodes_pos = sum(
        1 for r in rows if isinstance(r, dict) and isinstance(r.get("n_nodes"), int) and r["n_nodes"] > 0
    )

    values_all = cpr_values(rows, False)
    values_def = cpr_values(rows, True)
    if not values_all or not values_def:
        raise SystemExit("No PR rows available to plot.")

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(12.5, 12.0), sharex=True)
    draw_cpr_panel(ax0, rows, values_all, False, n_total, n_nodes_pos)
    draw_cpr_panel(ax1, rows, values_def, True, n_total, n_nodes_pos)
    fig.tight_layout()

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
