#!/usr/bin/env python3
"""
Merge PR metrics from every repo bundle under repos_analysed/, write a small JSON cache
under viz_output_all_repos/ at the project root (generated output), and plot combined histograms (fast restyle via --plot-only).

Run from the project root:
  python scripts/plot_all_repos_histograms.py
  python scripts/plot_all_repos_histograms.py --plot-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator


def apply_nice_style(fig: plt.Figure) -> None:
    """Make plots cleaner for reports (aggregate only)."""
    for ax in fig.axes:
        ax.set_facecolor("white")

        # More breathing room between ticks and labels.
        ax.tick_params(axis="x", which="major", pad=8)
        ax.tick_params(axis="y", which="major", pad=6)
        ax.xaxis.labelpad = 12
        ax.yaxis.labelpad = 10

        # Light horizontal grid; no vertical grid.
        ax.grid(True, which="major", axis="y", alpha=0.22, linewidth=0.7)
        ax.grid(False, axis="x")

        # Clean frame.
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        ax.tick_params(axis="both", which="major", labelsize=9.5, length=4)



from gh_pr_analysis.paths import pr_snapshots_dir_for_reading
from gh_pr_analysis.plots import fn_class_histogram as fn_plot
from gh_pr_analysis.plots import pyfile_histogram as py_plot
from gh_pr_analysis.plots import histogram_style as hs

SCHEMA_VERSION = 1

OUT_PYFILE = "all_repos_pr_pyfile_histogram.png"
OUT_FN_CLASS = "all_repos_pr_fn_class_changes_histogram.png"
DEFAULT_STATS_BASENAME = "aggregate_pr_stats.json"
DEFAULT_ALL_REPOS_VIZ_OUTPUT_DIR = _ROOT / "viz_output_all_repos"

# Aggregate pyfile histogram: pre-cap counts (default 25) so the bulk distribution
# uses the figure width; rare high counts merge into the last bin (raw max in stderr).
ALL_REPOS_PYFILE_HIST_X_MAX = 24


def safe_load_counts(index_path: Path) -> tuple[list[int], str | None]:
    """Like py_plot.load_counts but returns empty lists instead of exiting."""
    if not index_path.is_file():
        return [], None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"skip index {index_path}: {e}", file=sys.stderr)
        return [], None
    rows = data.get("pull_requests")
    if not isinstance(rows, list):
        print(f"skip index {index_path}: no pull_requests array", file=sys.stderr)
        return [], None
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


def is_bundle_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.name.startswith("."):
        return False
    index = path / "open_prs.json"
    if index.is_file():
        return True
    pr_root = pr_snapshots_dir_for_reading(path)
    try:
        if any(pr_root.glob("pr_*/snapshot.json")):
            return True
    except OSError:
        pass
    return False


def discover_bundles(repos_root: Path) -> list[Path]:
    if not repos_root.is_dir():
        return []
    return sorted(p for p in repos_root.iterdir() if is_bundle_dir(p))


def merge_bundles(
    bundles: list[Path], verbose: bool
) -> tuple[list[int], list[int], list[dict[str, Any]]]:
    merged_py: list[int] = []
    merged_fn: list[int] = []
    bundle_rows: list[dict[str, Any]] = []

    for bundle in bundles:
        row: dict[str, Any] = {
            "dir": bundle.name,
            "prs_indexed": 0,
            "snapshots_ok": 0,
            "snapshots_err": 0,
        }
        index_path = bundle / "open_prs.json"
        counts, _ = safe_load_counts(index_path)
        row["prs_indexed"] = len(counts)
        merged_py.extend(counts)
        if verbose and counts:
            print(f"  {bundle.name}: +INDEX {len(counts)} PRs", file=sys.stderr)

        pr_root = pr_snapshots_dir_for_reading(bundle)
        totals, n_ok, n_err = fn_plot.collect_totals(pr_root)
        row["snapshots_ok"] = n_ok
        row["snapshots_err"] = n_err
        merged_fn.extend(totals)
        if verbose and (n_ok or n_err):
            print(
                f"  {bundle.name}: +SNAPSHOTS ok={n_ok} err={n_err}",
                file=sys.stderr,
            )

        bundle_rows.append(row)

    return merged_py, merged_fn, bundle_rows


def write_stats_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2)
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def load_stats(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Stats file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit(f"Cannot read stats {path}: {e}") from e
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid stats JSON (expected object): {path}")
    return data


def _validate_int_list(data: dict[str, Any], key: str, stats_path: Path) -> list[int]:
    raw = data.get(key)
    if not isinstance(raw, list) or not all(isinstance(x, int) for x in raw):
        raise SystemExit(f"Missing or invalid {key} in {stats_path}")
    return raw



def plot_fn_class_broken(
    counts: list[int],
    *,
    percentile: float,
    slop: int,
    out_path: Path,
    title: str,
) -> None:
    # Fn/class has a long tail; show the head in detail and compress the tail into
    # a single last bin.
    FN_CLASS_X_MAX = 40

    raw = counts
    merged_pre = any(c > FN_CLASS_X_MAX for c in raw)
    clipped = [min(c, FN_CLASS_X_MAX) for c in raw]

    # Keep percentile logic only for logging/consistency; force the axis cap.
    _, series, merged_tail = hs.axis_hi_and_clip(clipped, percentile, slop)
    merged_tail = merged_tail or merged_pre
    hi = FN_CLASS_X_MAX
    bin_edges = [i - 0.5 for i in range(hi + 2)]

    fig, ax = plt.subplots(figsize=(14.0, 5.75))
    heights, _, patches = ax.hist(
        series, bins=bin_edges, edgecolor='black', alpha=0.85, color='tab:orange'
    )

    ax.set_title(f"Fn/class added/modified — {title}")
    ax.set_ylabel('PRs')

    xlabel = 'Fn/class added/modified'
    if merged_tail:
        xlabel = f"{xlabel} (last bin ≥{hi})"
    ax.set_xlabel(xlabel)

    ax.xaxis.set_major_locator(MultipleLocator(4))
    ax.set_xlim(-0.5, hi + 0.5)

    # Count+% labels for every non-empty bar.
    n_total = len(series)
    for patch, h in zip(patches, heights):
        h = float(h)
        if h <= 0:
            continue
        x = patch.get_x() + patch.get_width() / 2.0
        c = int(round(h))
        bin_idx = int(round(x))
        y_off = 26 if (bin_idx % 2) == 0 else 4
        ax.annotate(
            hs.bar_label_count_and_pct(c, n_total),
            xy=(x, h),
            xytext=(0, y_off),
            textcoords='offset points',
            ha='center',
            va='bottom',
            fontsize=7.2,
            color='black',
        )

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.20)
    lo, hi_y = ax.get_ylim()
    if hi_y > 0:
        ax.set_ylim(lo, hi_y * 1.22)

    apply_nice_style(fig)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Wrote {out_path}", file=sys.stderr)


def plot_histogram(
    counts: list[int],
    *,
    percentile: float,
    slop: int,
    render,
    out_path: Path,
    title: str,
    label_kind: str,
    pre_cap_x: int | None = None,
) -> None:
    if 'fn/class' in label_kind:
        plot_fn_class_broken(
            counts,
            percentile=percentile,
            slop=slop,
            out_path=out_path,
            title=title,
        )
        return

    raw = counts
    merged_pre = False
    if pre_cap_x is not None:
        merged_pre = any(c > pre_cap_x for c in raw)
        counts = [min(c, pre_cap_x) for c in raw]

    hi, series, merged_tail = py_plot.axis_hi_and_clip(counts, percentile, slop)
    merged_tail = merged_tail or merged_pre

    bin_edges = [i - 0.5 for i in range(hi + 2)]
    fig = render(series, hi, merged_tail, bin_edges, title)
    # Override verbose labels from shared plot helpers.
    ax = fig.axes[0] if fig.axes else None
    if ax is not None:
        ax.set_ylabel('PRs')
        # The render() functions prepend their own text; we pass a short suffix.
        # Keep x-labels short and consistent across aggregate plots.
        if 'pyfile' in label_kind:
            xlab = 'Python files added/modified'
        elif 'fn/class' in label_kind:
            xlab = 'Functions + classes touched'
        else:
            xlab = ax.get_xlabel()

        if merged_tail:
            xlab = f"{xlab} (last bin ≥{hi})"
        ax.set_xlabel(xlab)
        ax.set_xlim(-0.5, hi + 0.5)
    if ax is not None and 'fn/class' in label_kind:
        # X ticks every 4 (aggregate fn/class only).
        ax.xaxis.set_major_locator(MultipleLocator(4))

        # Replace shared bar labels: show count+% for every non-empty bar.
        for txt in list(ax.texts):
            txt.set_visible(False)

        patches = list(getattr(ax, 'patches', []))
        heights = [float(p.get_height()) for p in patches]
        n_total = int(round(sum(heights))) if heights else 0
        if n_total > 0:
            y_max = max(heights)
            inside_min_h = max(10.0, y_max * 0.12)
            for patch, h in zip(patches, heights):
                if h <= 0:
                    continue
                x = patch.get_x() + patch.get_width() / 2.0
                c = int(round(h))
                label = hs.bar_label_count_and_pct(c, n_total)
                if h >= inside_min_h:
                    # Inside tall bars: rotate to fit without horizontal collisions.
                    ax.annotate(
                        label,
                        xy=(x, h),
                        xytext=(0, -2),
                        textcoords='offset points',
                        ha='center',
                        va='top',
                        fontsize=7.6,
                        color='white',
                        rotation=90,
                    )
                else:
                    # Above short bars.
                    ax.annotate(
                        label,
                        xy=(x, h),
                        xytext=(0, 2),
                        textcoords='offset points',
                        ha='center',
                        va='bottom',
                        fontsize=7.4,
                        color='black',
                    )

    apply_nice_style(fig)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Wrote {out_path}", file=sys.stderr)
    if merged_tail:
        n_tail = sum(1 for c in raw if c >= hi)
        cap_note = f" pre-cap≤{pre_cap_x}" if pre_cap_x is not None else ""
        print(
            f"  ({label_kind}: x-axis capped at {hi}{cap_note}, {percentile:.0%}ile+1; "
            f"{n_tail} PRs in last bin; max raw {max(raw)})",
            file=sys.stderr,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    default_repos = _ROOT / "repos_analysed"
    p = argparse.ArgumentParser(
        description="Merge repo bundles under repos_root, cache stats JSON, plot aggregate histograms.",
    )
    p.add_argument(
        "--repos-root",
        type=Path,
        default=default_repos,
        help=f"Directory containing per-repo bundle folders (default: {default_repos})",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "Directory for PNGs and default stats path "
            f"(default: {DEFAULT_ALL_REPOS_VIZ_OUTPUT_DIR})"
        ),
    )
    p.add_argument(
        "--stats",
        type=Path,
        default=None,
        help=f"Aggregate JSON path (default: <out-dir>/{DEFAULT_STATS_BASENAME})",
    )
    p.add_argument(
        "--plot-only",
        action="store_true",
        help="Skip scanning repos; read --stats and write PNGs only.",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    repos_root: Path = args.repos_root.resolve()

    if args.out_dir is not None:
        out_dir = args.out_dir.resolve()
    elif args.plot_only and args.stats is not None:
        out_dir = args.stats.resolve().parent
    else:
        out_dir = DEFAULT_ALL_REPOS_VIZ_OUTPUT_DIR.resolve()

    if args.stats is not None:
        stats_path = args.stats.resolve()
    else:
        stats_path = out_dir / DEFAULT_STATS_BASENAME

    bundle_count = 0
    if args.plot_only:
        data = load_stats(stats_path)
        pycounts = _validate_int_list(
            data, "python_fn_class_modified_file_counts", stats_path
        )
        fntotals = _validate_int_list(
            data, "fn_class_change_totals_per_pr", stats_path
        )
        meta = data.get("_meta")
        if isinstance(meta, dict):
            bc = meta.get("bundle_count")
            if isinstance(bc, int):
                bundle_count = bc
    else:
        if not repos_root.is_dir():
            raise SystemExit(f"repos root not found: {repos_root}")
        bundles = discover_bundles(repos_root)
        if not bundles:
            raise SystemExit(
                f"No repo bundles under {repos_root} "
                "(expected subdirs with open_prs.json or snapshots)."
            )

        print(f"Scanning {len(bundles)} bundle(s) under {repos_root} …", file=sys.stderr)
        merged_py, merged_fn, bundle_rows = merge_bundles(bundles, args.verbose)

        if not merged_py:
            raise SystemExit(
                "No PR rows merged from any open_prs.json (check bundle indexes)."
            )

        bundle_count = len(bundle_rows)
        payload: dict[str, Any] = {
            "_meta": {
                "schema_version": SCHEMA_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "repos_root": str(repos_root),
                "bundle_count": bundle_count,
            },
            "bundles": bundle_rows,
            "python_fn_class_modified_file_counts": merged_py,
            "fn_class_change_totals_per_pr": merged_fn,
        }
        write_stats_atomic(stats_path, payload)
        print(f"Wrote {stats_path}", file=sys.stderr)

        pycounts = merged_py
        fntotals = merged_fn

    title_py = f"Python files added/modified — {bundle_count} repos · {len(pycounts)} PRs"
    title_fn = f"{bundle_count} repos · {len(fntotals)} PRs"

    plot_histogram(
        pycounts,
        percentile=py_plot.DISPLAY_PERCENTILE,
        slop=py_plot.TAIL_MERGE_SLOP,
        render=py_plot.render_histogram_figure,
        out_path=out_dir / OUT_PYFILE,
        title=title_py,
        label_kind="pyfile histogram",
        pre_cap_x=ALL_REPOS_PYFILE_HIST_X_MAX,
    )

    if fntotals:
        plot_histogram(
            fntotals,
            percentile=fn_plot.DISPLAY_PERCENTILE,
            slop=fn_plot.TAIL_MERGE_SLOP,
            render=fn_plot.render_histogram_figure,
            out_path=out_dir / OUT_FN_CLASS,
            title=title_fn,
            label_kind="fn/class histogram",
        )
    else:
        print(
            "No fn_class_change_totals (no snapshots merged); skip fn/class PNG.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
