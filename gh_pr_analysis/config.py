"""User-editable settings and API constants."""

from __future__ import annotations

from pathlib import Path

# Project root (parent of the gh_pr_analysis package)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Repo target for ``run_fetch_and_viz``. ``python main.py`` overwrites this each iteration with the
# repo from repos.json. For ad-hoc ``run_fetch_and_viz`` calls, set this or ``GITHUB_REPO`` in ``.env``.
GITHUB_REPO = "Significant-Gravitas/AutoGPT"
REPOS_ROOT = _PROJECT_ROOT / "repos"

# Limit open PRs processed (None = all). Use a small number when testing rate limits.
MAX_OPEN_PRS: int | None = 3

FETCH_COMMITS = False
FETCH_ISSUE_COMMENTS = False
FETCH_REVIEWS = False
FETCH_REVIEW_COMMENTS = False

RESUME_UNCHANGED = True
FORCE_FULL_REFRESH = False

SLEEP_AFTER_PR_SECONDS: float = 1.0

RUN_LOG_FILENAME = "fetch_run.log"
PR_SNAPSHOTS_SUBDIR = "snapshots"
VIZ_SUBDIR = "viz"

GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"
