"""GitHub REST API: JSON requests, pagination, raw file bytes."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from gh_pr_analysis.config import API_VERSION


def api_request(
    url: str,
    token: str | None,
    stats: dict[str, int] | None = None,
) -> tuple[Any, str | None]:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", API_VERSION)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if stats is not None:
                stats["github_rest"] = stats.get("github_rest", 0) + 1
            link = resp.headers.get("Link")
            body = resp.read().decode("utf-8")
            return json.loads(body), link
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} for {url}\n{detail}") from e


def paginate_list(
    url: str,
    token: str | None,
    max_items: int | None = None,
    stats: dict[str, int] | None = None,
) -> list[Any]:
    out: list[Any] = []
    next_url: str | None = url
    while next_url:
        data, link = api_request(next_url, token, stats)
        if isinstance(data, list):
            for item in data:
                out.append(item)
                if max_items is not None and len(out) >= max_items:
                    return out
        else:
            out.append(data)
            if max_items is not None and len(out) >= max_items:
                return out
        next_url = None
        if link and (max_items is None or len(out) < max_items):
            for part in link.split(","):
                if 'rel="next"' in part:
                    m = re.search(r"<([^>]+)>", part)
                    if m:
                        next_url = m.group(1)
                    break
    return out


def fetch_raw_bytes(
    url: str,
    token: str | None,
    stats: dict[str, int] | None = None,
) -> bytes:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        if stats is not None:
            stats["raw_fetches"] = stats.get("raw_fetches", 0) + 1
        return resp.read()


def api_usage_dict(stats: dict[str, int]) -> dict[str, int]:
    gr = int(stats.get("github_rest", 0))
    rw = int(stats.get("raw_fetches", 0))
    return {
        "github_rest_requests": gr,
        "raw_file_fetches": rw,
        "http_total": gr + rw,
    }
