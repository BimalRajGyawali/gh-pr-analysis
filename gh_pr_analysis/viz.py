"""Write matplotlib PNGs under viz/ from current index and snapshots."""

from __future__ import annotations

import importlib
import os
import sys


def generate_repo_histograms() -> None:
    """Run plot modules (same as CLI) to write viz/*.png for this repo bundle."""
    os.environ.setdefault("MPLBACKEND", "Agg")
    for mod_name in (
        "gh_pr_analysis.plots.pyfile_histogram",
        "gh_pr_analysis.plots.fn_class_histogram",
        "gh_pr_analysis.plots.pyfiles_vs_time",
    ):
        try:
            importlib.import_module(mod_name).main()
        except SystemExit as e:
            if e.code not in (0, None):
                print(
                    f"  warning: {mod_name} exited with {e.code!r} (viz may be stale)",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"  warning: {mod_name} failed: {e}", file=sys.stderr)
