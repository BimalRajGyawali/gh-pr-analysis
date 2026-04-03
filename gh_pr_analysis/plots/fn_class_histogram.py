"""
Histogram: open PRs vs total function+class change count per snapshot.

Reads snapshots under bundle/snapshots/pr_*/snapshot.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

import gh_pr_analysis.config as config
from gh_pr_analysis.paths import default_repo_bundle_dir, default_viz_dir, pr_snapshots_dir_for_reading
from gh_pr_analysis.plots.plot_common import try_repo_label
from gh_pr_analysis.plots.histogram_style import (
    annotate_histogram_bars,
    apply_histogram_x_axis,
    axis_hi_and_clip,
)

OUTPUT_BASENAME = "pr_fn_class_changes_histogram.png"
DISPLAY_PERCENTILE = 0.95
TAIL_MERGE_SLOP = 4


def total_fn_class_changes_from_snapshot(data: dict[str, object]) -> int:
    pya = data.get("python_fn_class_analysis")
    if not isinstance(pya, dict):
        return 0
    per_file = pya.get("per_file")
    if not isinstance(per_file, list):
        return 0
    total = 0
    for item in per_file:
        if not isinstance(item, dict):
            continue
        names = item.get("modified_functions_and_classes")
        if isinstance(names, list):
            total += len(names)
    return total


def collect_totals(pr_root: Path) -> tuple[list[int], int, int]:
    totals: list[int] = []
    n_ok = 0
    n_err = 0
    paths = sorted(pr_root.glob("pr_*/snapshot.json"))
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"skip {path}: {e}", file=sys.stderr)
            n_err += 1
            continue
        if not isinstance(raw, dict):
            n_err += 1
            continue
        totals.append(total_fn_class_changes_from_snapshot(raw))
        n_ok += 1
    return totals, n_ok, n_err


def render_histogram_figure(
    series: list[int],
    hi: int,
    merged_tail: bool,
    bin_edges: list[float],
    title_repo: str,
) -> plt.Figure:
    n_total = len(series)
    fig_w = 14.0 if hi > 45 else 12.0
    fig, ax = plt.subplots(figsize=(fig_w, 5.75))
    heights, _, patches = ax.hist(series, bins=bin_edges, edgecolor="black", alpha=0.85)

    apply_histogram_x_axis(
        ax,
        hi,
        merged_tail,
        "Functions + classes touched per PR (summed, bin width 1)",
    )

    y_top = annotate_histogram_bars(ax, patches, heights, n_total, hi)
    if y_top > 0:
        ax.set_ylim(0, y_top)

    ax.set_title(
        f"Open PRs by function + class change count (from snapshots) — {title_repo}"
    )
    ax.set_ylabel("Number of PRs")

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.18)
    for label in ax.get_xticklabels():
        label.set_rotation(40)
        label.set_ha("right")

    return fig


def run() -> None:
    repo_bundle = default_repo_bundle_dir()
    if not repo_bundle.is_dir():
        raise SystemExit(f"Repo bundle not found: {repo_bundle}")

    pr_root = pr_snapshots_dir_for_reading(repo_bundle)
    totals, n_ok, n_err = collect_totals(pr_root)
    if not totals:
        raise SystemExit(
            f"No snapshot.json under {pr_root}/pr_*/ (run `python main.py` first)."
        )

    print(
        f"Loaded {n_ok} snapshots" + (f", {n_err} read errors" if n_err else ""),
        file=sys.stderr,
    )

    hi, series, merged_tail = axis_hi_and_clip(totals, DISPLAY_PERCENTILE, TAIL_MERGE_SLOP)
    bin_edges = [i - 0.5 for i in range(hi + 2)]
    title_repo = try_repo_label(repo_bundle) or config.GITHUB_REPO

    fig = render_histogram_figure(series, hi, merged_tail, bin_edges, title_repo)
    viz = default_viz_dir()
    viz.mkdir(parents=True, exist_ok=True)
    out_path = viz / OUTPUT_BASENAME
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Wrote {out_path}", file=sys.stderr)

    if merged_tail:
        n_tail = sum(1 for c in totals if c >= hi)
        print(
            f"X-axis capped at {hi} ({DISPLAY_PERCENTILE:.0%}ile + 1, slop {TAIL_MERGE_SLOP}); "
            f"{n_tail} PRs merged into last bin (max total was {max(totals)}).",
            file=sys.stderr,
        )


if __name__ == "__main__":
    run()
