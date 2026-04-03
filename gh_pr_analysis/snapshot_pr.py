"""Fetch one PR snapshot (or resume unchanged) and write snapshot.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from gh_pr_analysis.config import (
    FETCH_COMMITS,
    FETCH_ISSUE_COMMENTS,
    FETCH_REVIEW_COMMENTS,
    FETCH_REVIEWS,
    FORCE_FULL_REFRESH,
    RESUME_UNCHANGED,
)
from gh_pr_analysis.downloads import download_pr_files
from gh_pr_analysis.github import api_usage_dict, paginate_list
from gh_pr_analysis.index_log import append_run_log, fetch_options_meta
from gh_pr_analysis.paths import pr_snapshots_dir
from gh_pr_analysis.python_diff import analyze_python_fn_class_changes


def try_resume_unchanged_pr_row(pr_root: Path, pr: dict[str, Any]) -> dict[str, Any] | None:
    """
    If snapshot.json exists and pull_request.updated_at and head.sha match the
    current PR from the API, return an index row without refetching.
    """
    if FORCE_FULL_REFRESH or not RESUME_UNCHANGED:
        return None
    pr_num = int(pr["number"])
    snap_path = pr_root / f"pr_{pr_num}" / "snapshot.json"
    if not snap_path.is_file():
        return None
    try:
        data = json.loads(snap_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    stored_pr = data.get("pull_request") or {}
    if stored_pr.get("updated_at") != pr.get("updated_at"):
        return None
    sh0 = (stored_pr.get("head") or {}).get("sha")
    sh1 = (pr.get("head") or {}).get("sha")
    if not sh1 or sh0 != sh1:
        return None
    rel_snap = f"pr_{pr_num}/snapshot.json"
    meta = data.get("_meta") or {}
    py_count = meta.get("python_fn_class_modified_file_count")
    if py_count is None:
        py_count = (data.get("python_fn_class_analysis") or {}).get("file_count", 0)
    return {
        "pull_number": pr_num,
        "title": pr.get("title"),
        "html_url": pr.get("html_url"),
        "state": pr.get("state"),
        "updated_at": pr.get("updated_at"),
        "user": (pr.get("user") or {}).get("login"),
        "python_fn_class_modified_file_count": py_count,
        "snapshot_path": rel_snap,
        "skipped_fetch": True,
    }


def fetch_snapshot_for_pr(
    owner: str,
    repo: str,
    api_base: str,
    token: str | None,
    repo_bundle: Path,
    pr: dict[str, Any],
) -> dict[str, Any]:
    """Build one PR snapshot on disk; return summary row for open_prs.json array."""
    pr_root = pr_snapshots_dir(repo_bundle)
    pr_root.mkdir(parents=True, exist_ok=True)
    pr_num = int(pr["number"])
    issue_num = pr_num
    pr_dir = pr_root / f"pr_{pr_num}"
    files_root = pr_dir / "files"
    pr_dir.mkdir(parents=True, exist_ok=True)

    resumed = try_resume_unchanged_pr_row(pr_root, pr)
    if resumed is not None:
        usage = api_usage_dict({"github_rest": 0, "raw_fetches": 0})
        row = {**resumed, "api_usage": usage}
        append_run_log(
            repo_bundle,
            {
                "event": "pr_skipped_resume",
                "pull_number": pr_num,
                "title": pr.get("title"),
                "html_url": pr.get("html_url"),
                "api_usage": usage,
            },
        )
        print(f"  PR #{pr_num} unchanged (resume), skipping fetch", file=sys.stderr)
        return row

    stats: dict[str, int] = {}
    raw_files = paginate_list(f"{api_base}/pulls/{pr_num}/files?per_page=100", token, stats=stats)
    file_dicts = [x for x in raw_files if isinstance(x, dict)]
    files_enriched = download_pr_files(file_dicts, files_root, token, stats)

    opts = fetch_options_meta()
    snapshot: dict[str, Any] = {
        "_meta": {
            "schema": "gh-pr-snapshot/v1",
            "repo": f"{owner}/{repo}",
            "pull_number": pr_num,
            "fetched_via": "GitHub REST API",
            "snapshot_dir": pr_dir.as_posix(),
            "fetch_options": opts,
            "note": (
                "PR head blobs are downloaded for each changed file (raw_url) so we can count .py files "
                "with at least one function or class touched (see python_fn_class_analysis). "
                "Each file entry may omit `patch` for binary/large files; GitHub may truncate huge diffs."
            ),
        },
        "pull_request": pr,
        "files": files_enriched,
        "commits": (
            paginate_list(f"{api_base}/pulls/{pr_num}/commits?per_page=100", token, stats=stats)
            if FETCH_COMMITS
            else []
        ),
        "issue_comments": (
            paginate_list(
                f"{api_base}/issues/{issue_num}/comments?per_page=100", token, stats=stats
            )
            if FETCH_ISSUE_COMMENTS
            else []
        ),
        "reviews": (
            paginate_list(f"{api_base}/pulls/{pr_num}/reviews?per_page=100", token, stats=stats)
            if FETCH_REVIEWS
            else []
        ),
        "review_comments": (
            paginate_list(
                f"{api_base}/pulls/{pr_num}/comments?per_page=100", token, stats=stats
            )
            if FETCH_REVIEW_COMMENTS
            else []
        ),
    }

    py_analysis = analyze_python_fn_class_changes(pr_dir, files_enriched)
    snapshot["_meta"]["api_usage"] = api_usage_dict(stats)
    snapshot["_meta"]["python_fn_class_modified_file_count"] = py_analysis["file_count"]
    snapshot["python_fn_class_analysis"] = py_analysis

    rel_snap = f"pr_{pr_num}/snapshot.json"
    out_path = pr_root / rel_snap
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    usage = api_usage_dict(stats)
    append_run_log(
        repo_bundle,
        {
            "event": "pr_fetched",
            "pull_number": pr_num,
            "title": pr.get("title"),
            "html_url": pr.get("html_url"),
            "changed_files": len(files_enriched),
            "python_fn_class_modified_file_count": py_analysis["file_count"],
            "api_usage": usage,
        },
    )

    return {
        "pull_number": pr_num,
        "title": pr.get("title"),
        "html_url": pr.get("html_url"),
        "state": pr.get("state"),
        "updated_at": pr.get("updated_at"),
        "user": (pr.get("user") or {}).get("login"),
        "python_fn_class_modified_file_count": py_analysis["file_count"],
        "snapshot_path": rel_snap,
        "api_usage": usage,
    }
