"""Fetch open PRs, update index, run histogram plots (``run_fetch_and_viz``)."""


from __future__ import annotations

import os
import sys
import time
from typing import Any

import gh_pr_analysis.config as cfg
from gh_pr_analysis.config import GITHUB_API
from gh_pr_analysis.github import api_usage_dict, paginate_list
from gh_pr_analysis.index_log import append_run_log, write_open_prs_index
from gh_pr_analysis.paths import per_repo_bundle_dir, pr_snapshots_dir
from gh_pr_analysis.repo_parse import parse_repo
from gh_pr_analysis.snapshot_pr import fetch_snapshot_for_pr
from gh_pr_analysis.viz import generate_repo_histograms


def run_fetch_and_viz() -> None:
    """Fetch open PRs for ``cfg.GITHUB_REPO``, update index, write viz/.

    Each iteration of ``main.py`` sets ``GITHUB_REPO`` from ``repos.json``. For ad-hoc ``run_fetch_and_viz`` calls, set ``GITHUB_REPO`` in ``.env`` or ``config.py``.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print(
            "Warning: No GITHUB_TOKEN or GH_TOKEN; rate limits are low for unauthenticated use.",
            file=sys.stderr,
        )

    owner, repo = parse_repo(cfg.GITHUB_REPO)
    print(
        f"Fetching all open PRs from {owner}/{repo} (GITHUB_REPO={cfg.GITHUB_REPO!r})",
        file=sys.stderr,
    )
    api_base = f"{GITHUB_API}/repos/{owner}/{repo}"

    list_stats: dict[str, int] = {}
    pulls = paginate_list(
        f"{api_base}/pulls?state=open&per_page=100&sort=updated&direction=desc",
        token,
        cfg.MAX_OPEN_PRS,
        stats=list_stats,
    )
    pull_items = [p for p in pulls if isinstance(p, dict)]
    if not pull_items:
        raise SystemExit(f"No open pull requests in {owner}/{repo}.")

    repo_key = f"{owner}_{repo}".replace("/", "_")
    repo_bundle = per_repo_bundle_dir(repo_key)
    repo_bundle.mkdir(parents=True, exist_ok=True)
    pr_snapshots_dir(repo_bundle).mkdir(parents=True, exist_ok=True)

    planned_total = len(pull_items)
    append_run_log(
        repo_bundle,
        {
            "event": "run_start",
            "repo": f"{owner}/{repo}",
            "planned_pr_total": planned_total,
            "api_usage": api_usage_dict(list_stats),
        },
    )
    cumulative: dict[str, int] = {
        "github_rest": list_stats.get("github_rest", 0),
        "raw_fetches": list_stats.get("raw_fetches", 0),
    }
    pull_rows: list[dict[str, Any]] = []
    index_path = repo_bundle / "open_prs.json"

    for i, pr in enumerate(pull_items, start=1):
        n = pr.get("number")
        print(f"[{i}/{planned_total}] PR #{n} — fetch & analyze …", file=sys.stderr)
        row = fetch_snapshot_for_pr(owner, repo, api_base, token, repo_bundle, pr)
        pull_rows.append(row)
        u = row.get("api_usage") or {}
        cumulative["github_rest"] = cumulative.get("github_rest", 0) + int(
            u.get("github_rest_requests", 0)
        )
        cumulative["raw_fetches"] = cumulative.get("raw_fetches", 0) + int(
            u.get("raw_file_fetches", 0)
        )
        write_open_prs_index(repo_bundle, owner, repo, pull_rows, planned_total)
        print(f"  → appended to {index_path} ({len(pull_rows)}/{planned_total})", file=sys.stderr)
        if cfg.SLEEP_AFTER_PR_SECONDS > 0 and i < planned_total:
            time.sleep(cfg.SLEEP_AFTER_PR_SECONDS)

    append_run_log(
        repo_bundle,
        {
            "event": "run_done",
            "repo": f"{owner}/{repo}",
            "planned_pr_total": planned_total,
            "pulls_processed": len(pull_rows),
            "api_usage": api_usage_dict(cumulative),
        },
    )
    print(f"Done. Index {index_path} ({len(pull_rows)} PRs)", file=sys.stderr)
    print("Writing viz/ histograms for repo …", file=sys.stderr)
    generate_repo_histograms()
    print("  → viz/ refreshed", file=sys.stderr)
