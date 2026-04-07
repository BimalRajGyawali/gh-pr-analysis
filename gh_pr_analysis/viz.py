"""Write matplotlib PNGs under viz/ from current index and snapshots."""

from __future__ import annotations

import importlib
import os
import sys

from gh_pr_analysis.timing_log import clock, elapsed_ms


def generate_repo_histograms() -> None:
    """Run plot modules (same as CLI) to write viz/*.png for this repo bundle."""
    os.environ.setdefault("MPLBACKEND", "Agg")
    for mod_name in (
        "gh_pr_analysis.plots.pyfile_histogram",
        "gh_pr_analysis.plots.fn_class_histogram",
        "gh_pr_analysis.plots.pyfiles_vs_time",
    ):
        t = clock()
        try:
            importlib.import_module(mod_name).run()
            ms = elapsed_ms(t)
            short = mod_name.rsplit(".", 1)[-1]
            print(f"  viz: {short} ({ms:.0f} ms)", file=sys.stderr)
        except SystemExit as e:
            if e.code not in (0, None):
                print(
                    f"  warning: {mod_name} exited with {e.code!r} (viz may be stale)",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"  warning: {mod_name} failed: {e}", file=sys.stderr)
