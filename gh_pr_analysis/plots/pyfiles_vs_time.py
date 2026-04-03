"""
Scatter: PR opened time vs count of .py paths in the diff (per snapshot).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

from gh_pr_analysis.config import GITHUB_REPO
from gh_pr_analysis.paths import default_repo_bundle_dir, default_viz_dir, pr_snapshots_dir_for_reading
from gh_pr_analysis.plots.plot_common import try_repo_label

OUTPUT_BASENAME = "pr_pyfiles_vs_time.png"
OPEN_TIME_FIELD = "created_at"
Y_VIEW_MAX = 32


def parse_github_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def count_py_files_in_diff(files: object) -> int:
    if not isinstance(files, list):
        return 0
    n = 0
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = entry.get("filename") or ""
        if isinstance(name, str) and name.endswith(".py"):
            n += 1
    return n


def collect_points(pr_root: Path) -> tuple[list[datetime], list[int], int, int]:
    dates: list[datetime] = []
    counts: list[int] = []
    n_ok = 0
    n_skip = 0
    for path in sorted(pr_root.glob("pr_*/snapshot.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"skip {path}: {e}", file=sys.stderr)
            n_skip += 1
            continue
        if not isinstance(raw, dict):
            n_skip += 1
            continue
        pr = raw.get("pull_request")
        if not isinstance(pr, dict):
            n_skip += 1
            continue
        ts = parse_github_datetime(pr.get(OPEN_TIME_FIELD))
        if ts is None:
            n_skip += 1
            continue
        n_py = count_py_files_in_diff(raw.get("files"))
        dates.append(ts)
        counts.append(n_py)
        n_ok += 1
    return dates, counts, n_ok, n_skip


def main() -> None:
    repo_bundle = default_repo_bundle_dir()
    if not repo_bundle.is_dir():
        raise SystemExit(f"Repo bundle not found: {repo_bundle}")

    pr_root = pr_snapshots_dir_for_reading(repo_bundle)
    dates, counts, n_ok, n_skip = collect_points(pr_root)
    if not dates:
        raise SystemExit(f"No usable snapshots under {pr_root}/pr_*/")

    print(
        f"Plotted {n_ok} PRs" + (f", skipped {n_skip}" if n_skip else ""),
        file=sys.stderr,
    )
    n_above = sum(1 for c in counts if c > Y_VIEW_MAX)
    if n_above:
        print(
            f"{n_above} PR(s) have >{Y_VIEW_MAX} Python files (points on top edge).",
            file=sys.stderr,
        )

    title_repo = try_repo_label(repo_bundle) or GITHUB_REPO

    fig, ax = plt.subplots(figsize=(12, 6.25), layout="constrained")
    ax.scatter(
        dates,
        counts,
        alpha=0.4,
        s=24,
        color="tab:blue",
        edgecolors="none",
    )
    ax.set_xlabel(f"PR opened ({OPEN_TIME_FIELD}, UTC)")
    ax.set_ylabel("Python files in PR diff (.py paths)")
    ax.set_title(
        f"Open PRs: time opened vs .py file count — {title_repo} (y: 0–{Y_VIEW_MAX})"
    )

    loc = mdates.AutoDateLocator(minticks=5, maxticks=11)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(
        ax.xaxis.get_majorticklabels(),
        rotation=38,
        ha="right",
        rotation_mode="anchor",
    )

    ax.set_ylim(-0.5, Y_VIEW_MAX)
    ax.yaxis.set_major_locator(MultipleLocator(1))
    ax.grid(True, which="major", axis="both", alpha=0.28, linewidth=0.6)
    ax.tick_params(axis="both", which="major", labelsize=9.5, length=5)
    ax.tick_params(axis="x", which="major", pad=8)

    viz = default_viz_dir()
    viz.mkdir(parents=True, exist_ok=True)
    out_path = viz / OUTPUT_BASENAME
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
