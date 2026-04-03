"""Download PR head file blobs under pr_<n>/files/."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from gh_pr_analysis.github import fetch_raw_bytes


def safe_relative_file_path(filename: str) -> Path:
    p = Path(filename)
    if p.is_absolute():
        raise ValueError(f"Absolute path not allowed: {filename!r}")
    for part in p.parts:
        if part == "..":
            raise ValueError(f"Path escapes root: {filename!r}")
    return p


def download_pr_files(
    files: list[dict[str, Any]],
    files_root: Path,
    token: str | None,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in files:
        entry = dict(item)
        rel_prefix = Path("files")
        name = entry.get("filename")
        raw_url = entry.get("raw_url")
        status = entry.get("status", "")

        if status == "removed":
            entry["local_path"] = None
            entry["download_error"] = "skipped_removed"
            enriched.append(entry)
            continue
        if not raw_url:
            entry["local_path"] = None
            entry["download_error"] = "no_raw_url"
            enriched.append(entry)
            continue

        try:
            rel_inside = safe_relative_file_path(str(name))
        except ValueError as e:
            entry["local_path"] = None
            entry["download_error"] = str(e)
            enriched.append(entry)
            continue

        dest = files_root / rel_inside
        dest.parent.mkdir(parents=True, exist_ok=True)
        local_rel = (rel_prefix / rel_inside).as_posix()

        try:
            body = fetch_raw_bytes(str(raw_url), token, stats)
            dest.write_bytes(body)
            entry["local_path"] = local_rel
            entry.pop("download_error", None)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            entry["local_path"] = None
            entry["download_error"] = f"{type(e).__name__}: {e}"

        enriched.append(entry)
    return enriched
