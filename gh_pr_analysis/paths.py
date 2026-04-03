"""Filesystem layout under REPOS_ROOT/<owner>_<repo>/."""

from __future__ import annotations

from pathlib import Path

from gh_pr_analysis.config import GITHUB_REPO, PR_SNAPSHOTS_SUBDIR, REPOS_ROOT, VIZ_SUBDIR
from gh_pr_analysis.repo_parse import parse_repo


def per_repo_bundle_dir(repo_key: str) -> Path:
    """Root folder for one GitHub repo: index, log, snapshots/, viz/."""
    return REPOS_ROOT / repo_key


def pr_snapshots_dir(bundle: Path) -> Path:
    """Directory that contains only pr_<number>/ snapshot trees."""
    return bundle / PR_SNAPSHOTS_SUBDIR


def default_repo_bundle_dir() -> Path:
    owner, repo = parse_repo(GITHUB_REPO)
    repo_key = f"{owner}_{repo}".replace("/", "_")
    return per_repo_bundle_dir(repo_key)


def default_open_prs_path() -> Path:
    return default_repo_bundle_dir() / "open_prs.json"


def default_viz_dir() -> Path:
    return default_repo_bundle_dir() / VIZ_SUBDIR


def pr_snapshots_dir_for_reading(bundle: Path) -> Path:
    """
    Prefer bundle/snapshots/pr_* (new layout). If snapshots/ is missing or empty of pr_*,
    fall back to legacy bundle/pr_* next to open_prs.json.
    """
    inner = pr_snapshots_dir(bundle)
    if inner.is_dir():
        for p in inner.iterdir():
            if p.is_dir() and p.name.startswith("pr_"):
                return inner
    for p in bundle.iterdir():
        if p.is_dir() and p.name.startswith("pr_"):
            return bundle
    return inner
