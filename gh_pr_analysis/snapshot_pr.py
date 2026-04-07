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
from gh_pr_analysis.timing_log import clock, elapsed_ms


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

    t_wall = clock()
    resumed = try_resume_unchanged_pr_row(pr_root, pr)
    if resumed is not None:
        usage = api_usage_dict({"github_rest": 0, "raw_fetches": 0})
        timings_ms = {"resume_check_ms": elapsed_ms(t_wall), "total_ms": elapsed_ms(t_wall)}
        row = {**resumed, "api_usage": usage, "timings_ms": timings_ms}
        append_run_log(
            repo_bundle,
            {
                "event": "pr_skipped_resume",
                "pull_number": pr_num,
                "title": pr.get("title"),
                "html_url": pr.get("html_url"),
                "api_usage": usage,
                "timings_ms": timings_ms,
            },
        )
        print(
            f"  PR #{pr_num} unchanged (resume), skipping fetch ({timings_ms['total_ms']:.0f} ms)",
            file=sys.stderr,
            flush=True,
        )
        return row

    stats: dict[str, int] = {}
    timings_ms: dict[str, float] = {}
    pl = f"PR #{pr_num}"

    print(f"  [{pl}] step: list changed files (REST) …", file=sys.stderr, flush=True)
    t = clock()
    raw_files = paginate_list(
        f"{api_base}/pulls/{pr_num}/files?per_page=100",
        token,
        stats=stats,
        progress_label=f"{pl} files",
    )
    timings_ms["list_pr_files_ms"] = elapsed_ms(t)

    t = clock()
    file_dicts = [x for x in raw_files if isinstance(x, dict)]
    files_enriched = download_pr_files(
        file_dicts,
        files_root,
        token,
        stats,
        progress_prefix=f"{pl} raw",
    )
    timings_ms["download_raw_files_ms"] = elapsed_ms(t)

    commits: list[Any] = []
    if FETCH_COMMITS:
        print(f"  [{pl}] step: fetch commits …", file=sys.stderr, flush=True)
        t = clock()
        commits = paginate_list(
            f"{api_base}/pulls/{pr_num}/commits?per_page=100",
            token,
            stats=stats,
            progress_label=f"{pl} commits",
        )
        timings_ms["fetch_commits_ms"] = elapsed_ms(t)

    issue_comments: list[Any] = []
    if FETCH_ISSUE_COMMENTS:
        print(f"  [{pl}] step: issue comments …", file=sys.stderr, flush=True)
        t = clock()
        issue_comments = paginate_list(
            f"{api_base}/issues/{issue_num}/comments?per_page=100",
            token,
            stats=stats,
            progress_label=f"{pl} issue_comments",
        )
        timings_ms["fetch_issue_comments_ms"] = elapsed_ms(t)

    reviews: list[Any] = []
    if FETCH_REVIEWS:
        print(f"  [{pl}] step: reviews …", file=sys.stderr, flush=True)
        t = clock()
        reviews = paginate_list(
            f"{api_base}/pulls/{pr_num}/reviews?per_page=100",
            token,
            stats=stats,
            progress_label=f"{pl} reviews",
        )
        timings_ms["fetch_reviews_ms"] = elapsed_ms(t)

    review_comments: list[Any] = []
    if FETCH_REVIEW_COMMENTS:
        print(f"  [{pl}] step: review comments …", file=sys.stderr, flush=True)
        t = clock()
        review_comments = paginate_list(
            f"{api_base}/pulls/{pr_num}/comments?per_page=100",
            token,
            stats=stats,
            progress_label=f"{pl} review_comments",
        )
        timings_ms["fetch_review_comments_ms"] = elapsed_ms(t)

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
        "commits": commits,
        "issue_comments": issue_comments,
        "reviews": reviews,
        "review_comments": review_comments,
    }

    print(f"  [PR #{pr_num}] step: python fn/class analysis …", file=sys.stderr, flush=True)
    t = clock()
    py_analysis = analyze_python_fn_class_changes(
        pr_dir,
        files_enriched,
        log_prefix=f"PR #{pr_num} py",
    )
    timings_ms["analyze_python_ms"] = elapsed_ms(t)

    snapshot["_meta"]["api_usage"] = api_usage_dict(stats)
    snapshot["_meta"]["python_fn_class_modified_file_count"] = py_analysis["file_count"]
    snapshot["python_fn_class_analysis"] = py_analysis

    rel_snap = f"pr_{pr_num}/snapshot.json"
    out_path = pr_root / rel_snap
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"  [PR #{pr_num}] step: write snapshot.json ({len(files_enriched)} files in index) …",
        file=sys.stderr,
        flush=True,
    )
    t = clock()
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    timings_ms["write_snapshot_ms"] = elapsed_ms(t)
    timings_ms["total_ms"] = elapsed_ms(t_wall)
    snapshot["_meta"]["timings_ms"] = timings_ms

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
            "timings_ms": timings_ms,
        },
    )

    parts = [
        f"list_pr_files={timings_ms['list_pr_files_ms']:.0f}ms",
        f"download_raw={timings_ms['download_raw_files_ms']:.0f}ms",
        f"analyze_py={timings_ms['analyze_python_ms']:.0f}ms",
        f"write={timings_ms['write_snapshot_ms']:.0f}ms",
        f"total={timings_ms['total_ms']:.0f}ms",
    ]
    print(f"  timings: {' | '.join(parts)}", file=sys.stderr, flush=True)

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
        "timings_ms": timings_ms,
    }
