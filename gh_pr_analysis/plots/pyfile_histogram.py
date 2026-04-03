"""
Histogram of open PRs by python_fn_class_modified_file_count (from open_prs.json).

Plots use the repo bundle on disk; title falls back to config.GITHUB_REPO (set by ``main.py`` / ``repos.json`` or ``GITHUB_REPO`` in ``.env``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

import gh_pr_analysis.config as config
from gh_pr_analysis.paths import default_open_prs_path, default_viz_dir
from gh_pr_analysis.plots.histogram_style import (
    annotate_histogram_bars,
    apply_histogram_x_axis,
    axis_hi_and_clip,
)

OUTPUT_BASENAME = "pr_pyfile_histogram.png"
DISPLAY_PERCENTILE = 0.99
TAIL_MERGE_SLOP = 5


def load_counts(index_path: Path) -> tuple[list[int], str | None]:
    data = json.loads(index_path.read_text(encoding="utf-8"))
    rows = data.get("pull_requests")
    if not isinstance(rows, list):
        raise SystemExit(f"No pull_requests array in {index_path}")
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    repo_label = meta.get("repo")
    if not isinstance(repo_label, str):
        repo_label = None
    counts: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        v = row.get("python_fn_class_modified_file_count", 0)
        try:
            counts.append(int(v))
        except (TypeError, ValueError):
            counts.append(0)
    return counts, repo_label


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
        "Python files (function/class touched, bin width 1)",
    )

    y_top = annotate_histogram_bars(ax, patches, heights, n_total, hi)
    if y_top > 0:
        ax.set_ylim(0, y_top)

    ax.set_title(f"Open PRs by Python touched-file count — {title_repo}")
    ax.set_ylabel("Number of PRs")

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.18)
    for label in ax.get_xticklabels():
        label.set_rotation(40)
        label.set_ha("right")

    return fig


def run() -> None:
    index_path = default_open_prs_path()
    if not index_path.is_file():
        raise SystemExit(
            f"Index not found: {index_path}\n(Run ``python main.py`` from the project root first.)"
        )

    counts, repo_meta = load_counts(index_path)
    if not counts:
        raise SystemExit(f"No pull request rows in {index_path}")

    hi, series, merged_tail = axis_hi_and_clip(counts, DISPLAY_PERCENTILE, TAIL_MERGE_SLOP)
    bin_edges = [i - 0.5 for i in range(hi + 2)]
    title_repo = repo_meta or config.GITHUB_REPO

    fig = render_histogram_figure(series, hi, merged_tail, bin_edges, title_repo)
    viz = default_viz_dir()
    viz.mkdir(parents=True, exist_ok=True)
    out_path = viz / OUTPUT_BASENAME
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Wrote {out_path}", file=sys.stderr)

    if merged_tail:
        n_tail = sum(1 for c in counts if c >= hi)
        print(
            f"X-axis capped at {hi} ({DISPLAY_PERCENTILE:.0%}ile + 1); "
            f"{n_tail} PRs merged into last bin (max count was {max(counts)}).",
            file=sys.stderr,
        )


if __name__ == "__main__":
    run()
