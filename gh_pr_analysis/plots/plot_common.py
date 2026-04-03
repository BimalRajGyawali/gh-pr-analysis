"""Shared helpers for plot scripts."""

from __future__ import annotations

import json
from pathlib import Path


def try_repo_label(repo_bundle: Path) -> str | None:
    idx = repo_bundle / "open_prs.json"
    if not idx.is_file():
        return None
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    meta = data.get("_meta")
    if isinstance(meta, dict):
        r = meta.get("repo")
        if isinstance(r, str):
            return r
    return None
