"""Parse owner/repo from a GitHub URL or owner/repo string."""

from __future__ import annotations

import re


def parse_repo(spec: str) -> tuple[str, str]:
    spec = spec.strip().rstrip("/")
    if "github.com" in spec:
        m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", spec)
        if not m:
            raise ValueError(f"Could not parse repo from: {spec}")
        return m.group(1), re.sub(r"\.git$", "", m.group(2))
    parts = spec.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Use owner/repo or https://github.com/owner/repo")
    return parts[0], parts[1]
