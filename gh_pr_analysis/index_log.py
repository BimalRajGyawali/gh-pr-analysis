"""open_prs.json index and append-only fetch_run.log."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_pr_analysis.config import (
    FETCH_COMMITS,
    FETCH_ISSUE_COMMENTS,
    FETCH_REVIEW_COMMENTS,
    FETCH_REVIEWS,
    FORCE_FULL_REFRESH,
    RESUME_UNCHANGED,
    RUN_LOG_FILENAME,
)
from gh_pr_analysis.paths import pr_snapshots_dir


def fetch_options_meta() -> dict[str, Any]:
    return {
        "fetch_commits": FETCH_COMMITS,
        "fetch_issue_comments": FETCH_ISSUE_COMMENTS,
        "fetch_reviews": FETCH_REVIEWS,
        "fetch_review_comments": FETCH_REVIEW_COMMENTS,
        "resume_unchanged": RESUME_UNCHANGED and not FORCE_FULL_REFRESH,
    }


def append_run_log(repo_bundle: Path, record: dict[str, Any]) -> None:
    line = {"ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **record}
    with (repo_bundle / RUN_LOG_FILENAME).open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def write_open_prs_index(
    repo_bundle: Path,
    owner: str,
    repo: str,
    pull_rows: list[dict[str, Any]],
    planned_total: int,
) -> Path:
    """Persist open_prs.json after each PR so progress survives interruption."""
    done = len(pull_rows)
    for i, row in enumerate(pull_rows, start=1):
        row["serial"] = i
    pr_root = pr_snapshots_dir(repo_bundle)
    index_path = repo_bundle / "open_prs.json"
    index_doc = {
        "_meta": {
            "schema": "gh-pr-open-snapshots/v1",
            "repo": f"{owner}/{repo}",
            "open_pr_count": done,
            "planned_pr_total": planned_total,
            "in_progress": done < planned_total,
            "repo_data_dir": repo_bundle.as_posix(),
            "repo_snapshot_dir": pr_root.as_posix(),
            "fetch_options": fetch_options_meta(),
            "note": (
                "Updated after each PR: fetch that PR → analyze (python_fn_class) → append row here. "
                "If the run stops early, in_progress is true and pull_requests may be partial. "
                "Full snapshots live at snapshot_path under repo_snapshot_dir (snapshots/pr_* only); "
                "open_prs.json and fetch_run.log live in repo_data_dir. skipped_fetch = resume."
            ),
        },
        "pull_requests": pull_rows,
    }
    index_path.write_text(json.dumps(index_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return index_path
