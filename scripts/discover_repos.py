#!/usr/bin/env python3
"""
Search GitHub for popular Python repositories (filters tutorials, low contributors, Python byte share).

Standalone tool — not used by ``python main.py``. Run from the project root:
  python scripts/discover_repos.py
  python scripts/discover_repos.py --json   # one JSON object per line for piping

Keeps repos that: match ``language:python`` search, have **≥90% Python by bytes** (GitHub
``/languages`` API) by default, **≥2 contributors** by default, and pass text deny-lists.

Output is ``owner/repo`` lines you can paste into ``repos.json``. Uses GITHUB_TOKEN or GH_TOKEN
from the environment or ``.env`` at the project root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gh_pr_analysis.config import GITHUB_API
from gh_pr_analysis.github import api_request

_DEFAULT_NAME_DENY = (
    "tutorial",
    "tutorials",
    "bootcamp",
    "course-material",
    "learn-python",
    "100-days",
    "30-days",
    "complete-python",
    "public-apis",
    "publicapis",
    "awesome-list",
    "awesome-api",
    "free-api",
)
_DEFAULT_DESC_DENY = (
    "tutorial for",
    "this repo is a tutorial",
    "course project",
    "udemy",
    "bootcamp",
    "collective list",
    "list of free apis",
    "list of public apis",
    "list of apis for",
    "curated list of",
    "collection of apis",
    "collection of free apis",
    "free apis for",
    "a curated list",
)


def build_search_query(
    min_stars: int,
    exclude_fork: bool,
    exclude_archived: bool,
    extra_topics_exclude: list[str],
) -> str:
    parts = ["language:python", f"stars:>{min_stars}"]
    if exclude_fork:
        parts.append("fork:false")
    if exclude_archived:
        parts.append("archived:false")
    for t in (
        "tutorial",
        "demo",
        "example",
        "public-apis",
        "awesome-list",
        "api-list",
        "free-api",
    ):
        parts.append(f"-topic:{t}")
    for t in extra_topics_exclude:
        t = t.strip().lstrip("-")
        if t:
            parts.append(f"-topic:{t}")
    return " ".join(parts)


def search_repositories(
    query: str,
    token: str | None,
    max_items: int,
    sleep_between_pages: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    per_page = min(100, max(1, max_items))

    while len(out) < max_items and page <= 10:
        q_enc = urllib.parse.quote_plus(query)
        url = (
            f"{GITHUB_API}/search/repositories?q={q_enc}"
            f"&sort=stars&order=desc&per_page={per_page}&page={page}"
        )
        data, _ = api_request(url, token)
        if not isinstance(data, dict):
            break
        items = data.get("items")
        if not isinstance(items, list) or not items:
            break
        for it in items:
            if isinstance(it, dict):
                out.append(it)
                if len(out) >= max_items:
                    return out
        if len(items) < per_page:
            break
        page += 1
        if sleep_between_pages > 0:
            time.sleep(sleep_between_pages)
    return out


def has_at_least_n_contributors(
    owner: str,
    repo: str,
    token: str | None,
    n: int,
) -> bool:
    o = urllib.parse.quote(owner, safe="")
    r = urllib.parse.quote(repo, safe="")
    url = f"{GITHUB_API}/repos/{o}/{r}/contributors?per_page={max(n, 2)}&anon=1"
    data, _ = api_request(url, token)
    return isinstance(data, list) and len(data) >= n


def python_byte_share(owner: str, repo: str, token: str | None) -> float | None:
    """Fraction of repo bytes in ``Python`` from GET /repos/{owner}/{repo}/languages."""
    o = urllib.parse.quote(owner, safe="")
    r = urllib.parse.quote(repo, safe="")
    url = f"{GITHUB_API}/repos/{o}/{r}/languages"
    data, _ = api_request(url, token)
    if not isinstance(data, dict) or not data:
        return None
    total = 0
    python_bytes = 0
    for lang, nb in data.items():
        if not isinstance(lang, str):
            continue
        try:
            b = int(nb)
        except (TypeError, ValueError):
            continue
        total += b
        if lang == "Python":
            python_bytes = b
    if total <= 0:
        return None
    return python_bytes / total


def passes_text_filters(
    full_name: str,
    description: str | None,
    name_deny: tuple[str, ...],
    desc_deny: tuple[str, ...],
) -> bool:
    name_l = full_name.lower()
    desc_l = (description or "").lower()
    if any(s in name_l for s in name_deny):
        return False
    if any(s in desc_l for s in desc_deny):
        return False
    return True


def discover_accepted(
    *,
    token: str | None,
    min_stars: int,
    min_contributors: int,
    max_candidates: int,
    sleep_search: float,
    sleep_contributors: float,
    include_forks: bool,
    include_archived: bool,
    extra_topics_exclude: list[str],
    min_python_fraction: float,
    max_accepted: int | None = None,
) -> list[dict[str, Any]]:
    query = build_search_query(
        min_stars,
        exclude_fork=not include_forks,
        exclude_archived=not include_archived,
        extra_topics_exclude=extra_topics_exclude,
    )
    candidates = search_repositories(
        query,
        token,
        max_items=max_candidates,
        sleep_between_pages=sleep_search,
    )
    accepted: list[dict[str, Any]] = []
    for it in candidates:
        if max_accepted is not None and len(accepted) >= max_accepted:
            break
        fn = it.get("full_name")
        if not isinstance(fn, str) or "/" not in fn:
            continue
        owner, repo = fn.split("/", 1)
        desc = it.get("description")
        desc_s = desc if isinstance(desc, str) else None

        if not passes_text_filters(fn, desc_s, _DEFAULT_NAME_DENY, _DEFAULT_DESC_DENY):
            print(f"  skip (text filter): {fn}", file=sys.stderr)
            continue

        share = python_byte_share(owner, repo, token)
        if share is None:
            print(f"  skip (no language stats): {fn}", file=sys.stderr)
            if sleep_contributors > 0:
                time.sleep(sleep_contributors)
            continue
        if share < min_python_fraction:
            print(
                f"  skip (Python {share * 100:.1f}% by bytes < {min_python_fraction * 100:.0f}%): {fn}",
                file=sys.stderr,
            )
            if sleep_contributors > 0:
                time.sleep(sleep_contributors)
            continue

        if not has_at_least_n_contributors(owner, repo, token, min_contributors):
            print(f"  skip (<{min_contributors} contributors): {fn}", file=sys.stderr)
            if sleep_contributors > 0:
                time.sleep(sleep_contributors)
            continue

        row = {
            "full_name": fn,
            "stars": it.get("stargazers_count"),
            "description": desc_s,
            "html_url": it.get("html_url"),
            "python_byte_fraction": round(share, 4),
        }
        accepted.append(row)
        if sleep_contributors > 0:
            time.sleep(sleep_contributors)
    return accepted


def run_discover(args: argparse.Namespace) -> None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print(
            "Warning: no GITHUB_TOKEN or GH_TOKEN; search rate limits are very low.\n",
            file=sys.stderr,
        )

    query = build_search_query(
        args.min_stars,
        exclude_fork=not args.include_forks,
        exclude_archived=not args.include_archived,
        extra_topics_exclude=args.exclude_topic,
    )
    print(f"Search query: {query}", file=sys.stderr)

    accepted = discover_accepted(
        token=token,
        min_stars=args.min_stars,
        min_contributors=args.min_contributors,
        max_candidates=args.max_candidates,
        sleep_search=args.sleep_search,
        sleep_contributors=args.sleep_contributors,
        include_forks=args.include_forks,
        include_archived=args.include_archived,
        extra_topics_exclude=args.exclude_topic,
        min_python_fraction=args.min_python_fraction,
        max_accepted=None,
    )
    print(f"Search pipeline accepted {len(accepted)} repos.", file=sys.stderr)

    if args.json:
        for row in accepted:
            print(json.dumps(row, ensure_ascii=False))
    else:
        for row in accepted:
            print(row["full_name"])

    print(f"\nKept {len(accepted)} repos.", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/discover_repos.py",
        description=(
            "Search GitHub for Python repos; print owner/repo lines (or --json). "
            "Filters: Python byte share (default 90%), contributors (default 2+), text deny-lists. "
            "Run from project root. Does not run the PR analysis pipeline."
        ),
    )
    parser.add_argument("--min-stars", type=int, default=10000, help="Minimum stars")
    parser.add_argument(
        "--min-contributors",
        type=int,
        default=2,
        help="Minimum distinct contributors (default 2)",
    )
    parser.add_argument(
        "--min-python-fraction",
        type=float,
        default=0.9,
        metavar="F",
        help="Min share of Python by bytes from /languages API (0-1, default 0.9 = 90%%)",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=80,
        help="Max search results to filter (default 80)",
    )
    parser.add_argument("--sleep-search", type=float, default=2.0, help="Seconds between search pages")
    parser.add_argument(
        "--sleep-contributors",
        type=float,
        default=0.15,
        help="Seconds after each per-repo API check (languages + contributors)",
    )
    parser.add_argument("--include-forks", action="store_true", help="Include forks in search")
    parser.add_argument("--include-archived", action="store_true", help="Include archived repos in search")
    parser.add_argument("--exclude-topic", action="append", default=[], metavar="TOPIC", help="Extra -topic: exclude")
    parser.add_argument("--json", action="store_true", help="Print one JSON object per line")
    return parser


def main() -> None:
    from gh_pr_analysis.dotenv import load_dotenv_simple

    load_dotenv_simple(_ROOT / ".env")
    args = build_parser().parse_args()
    if not 0.0 <= args.min_python_fraction <= 1.0:
        raise SystemExit("--min-python-fraction must be between 0 and 1")
    if args.min_contributors < 1:
        raise SystemExit("--min-contributors must be at least 1")
    run_discover(args)


if __name__ == "__main__":
    main()
