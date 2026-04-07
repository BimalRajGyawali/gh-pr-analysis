"""Download PR head file blobs under pr_<n>/files/."""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from gh_pr_analysis.github import fetch_raw_bytes
from gh_pr_analysis.timing_log import clock, elapsed_ms


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
    *,
    progress_prefix: str | None = None,
) -> list[dict[str, Any]]:
    to_fetch = 0
    for item in files:
        st = item.get("status", "")
        if st == "removed" or not item.get("raw_url"):
            continue
        name = item.get("filename")
        if not name:
            continue
        try:
            safe_relative_file_path(str(name))
        except ValueError:
            continue
        to_fetch += 1

    if progress_prefix:
        print(
            f"  [{progress_prefix}] raw downloads: {to_fetch} file(s) to fetch "
            f"({len(files)} changed-file entries) …",
            file=sys.stderr,
            flush=True,
        )

    enriched: list[dict[str, Any]] = []
    fetch_idx = 0
    rel_prefix = Path("files")
    for item in files:
        entry = dict(item)
        name = entry.get("filename")
        raw_url = entry.get("raw_url")
        status = entry.get("status", "")

        if status == "removed":
            entry["local_path"] = None
            entry["download_error"] = "skipped_removed"
            if progress_prefix and name:
                print(
                    f"  [{progress_prefix}] skip removed: {name}",
                    file=sys.stderr,
                    flush=True,
                )
            enriched.append(entry)
            continue
        if not raw_url:
            entry["local_path"] = None
            entry["download_error"] = "no_raw_url"
            if progress_prefix and name:
                print(
                    f"  [{progress_prefix}] skip no raw_url: {name}",
                    file=sys.stderr,
                    flush=True,
                )
            enriched.append(entry)
            continue

        try:
            rel_inside = safe_relative_file_path(str(name))
        except ValueError as e:
            entry["local_path"] = None
            entry["download_error"] = str(e)
            if progress_prefix and name:
                print(
                    f"  [{progress_prefix}] skip bad path: {name} ({e})",
                    file=sys.stderr,
                    flush=True,
                )
            enriched.append(entry)
            continue

        dest = files_root / rel_inside
        dest.parent.mkdir(parents=True, exist_ok=True)
        local_rel = (rel_prefix / rel_inside).as_posix()

        fetch_idx += 1
        if progress_prefix:
            print(
                f"  [{progress_prefix}] GET {fetch_idx}/{to_fetch} {name} …",
                file=sys.stderr,
                flush=True,
            )
        try:
            t0 = clock()
            body = fetch_raw_bytes(str(raw_url), token, stats)
            ms = elapsed_ms(t0)
            dest.write_bytes(body)
            entry["local_path"] = local_rel
            entry.pop("download_error", None)
            if progress_prefix:
                print(
                    f"  [{progress_prefix}] OK {fetch_idx}/{to_fetch} {name} "
                    f"({len(body)} bytes, {ms:.0f}ms)",
                    file=sys.stderr,
                    flush=True,
                )
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            entry["local_path"] = None
            entry["download_error"] = f"{type(e).__name__}: {e}"
            if progress_prefix:
                print(
                    f"  [{progress_prefix}] FAIL {fetch_idx}/{to_fetch} {name}: {entry['download_error']}",
                    file=sys.stderr,
                    flush=True,
                )

        enriched.append(entry)
    return enriched
