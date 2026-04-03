"""CLI: read repos.json → for each repo, fetch open PRs, analyze, viz."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import gh_pr_analysis.config as cfg
from gh_pr_analysis.dotenv import load_dotenv_simple
from gh_pr_analysis.pipeline import run_fetch_and_viz

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPOS_JSON = _PROJECT_ROOT / "repos.json"


def existing_repo_full_names_lower(repos_root: Path) -> set[str]:
    out: set[str] = set()
    if not repos_root.is_dir():
        return out
    for bundle in repos_root.iterdir():
        if not bundle.is_dir():
            continue
        p = bundle / "open_prs.json"
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        meta = data.get("_meta")
        if isinstance(meta, dict):
            r = meta.get("repo")
            if isinstance(r, str) and "/" in r:
                out.add(r.lower())
    return out


def load_repos_from_file(path: Path) -> list[str]:
    if not path.is_file():
        raise SystemExit(
            f"Missing {path}. Copy repos.example.json to repos.json and list owner/repo strings."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON in {path}: {e}") from e

    if isinstance(raw, list):
        items: list[object] = raw
    elif isinstance(raw, dict):
        r = raw.get("repos")
        if isinstance(r, list):
            items = r
        else:
            raise SystemExit(
                f'{path} must be a JSON array or an object with a "repos" array.'
            )
    else:
        raise SystemExit(
            f'{path} must be a JSON array or an object with a "repos" array.'
        )

    out: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, str):
            raise SystemExit(
                f'{path}: entry {i} is not a string (expected "owner/repo").'
            )
        s = item.strip()
        if "/" not in s:
            raise SystemExit(f"{path}: entry {i} {s!r} must look like owner/repo.")
        owner, name = s.split("/", 1)
        if not owner.strip() or not name.strip():
            raise SystemExit(
                f"{path}: entry {i} {s!r} must have non-empty owner and repo name."
            )
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)

    if not out:
        raise SystemExit(f"{path} has no valid repo entries.")
    return out


def run_pipeline(args: argparse.Namespace) -> None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print(
            "Warning: no GITHUB_TOKEN or GH_TOKEN; fetch limits are very low.\n",
            file=sys.stderr,
        )

    repos = load_repos_from_file(REPOS_JSON)
    on_disk = (
        set()
        if args.no_skip_existing_bundles
        else existing_repo_full_names_lower(cfg.REPOS_ROOT)
    )
    session: set[str] = set()
    prev_repo = cfg.GITHUB_REPO
    prev_max = cfg.MAX_OPEN_PRS

    try:
        cfg.MAX_OPEN_PRS = args.max_open_prs
        total = len(repos)
        for i, pick in enumerate(repos, start=1):
            blocked = on_disk | session
            low = pick.lower()
            if low in blocked:
                print(
                    f"\n=== ({i}/{total}) Skip (already known): {pick} ===\n",
                    file=sys.stderr,
                )
                continue

            session.add(low)
            cfg.GITHUB_REPO = pick
            print(
                f"\n=== ({i}/{total}) Process PRs + viz: {pick} ===\n",
                file=sys.stderr,
            )
            try:
                run_fetch_and_viz()
            except SystemExit as e:
                if e.code not in (0, None):
                    print(
                        f"  stopped with exit code {e.code!r}, continuing to next repo …",
                        file=sys.stderr,
                    )
    finally:
        cfg.GITHUB_REPO = prev_repo
        cfg.MAX_OPEN_PRS = prev_max

    print(f"\nDone ({len(repos)} repo(s) in {REPOS_JSON.name}).", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "For each owner/repo in repos.json: fetch open PRs, analyze, write viz/. "
            "Run from the project root; set GITHUB_TOKEN or GH_TOKEN in .env."
        ),
    )
    parser.add_argument(
        "--max-open-prs",
        type=int,
        default=None,
        metavar="N",
        help="Max open PRs per repo (default: unlimited)",
    )
    parser.add_argument(
        "--no-skip-existing-bundles",
        action="store_true",
        help="Do not skip repos that already have repos/*/open_prs.json",
    )
    return parser


def run(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if argv and argv[0] in ("-h", "--help"):
        parser.print_help()
        return

    load_dotenv_simple(_PROJECT_ROOT / ".env")
    args = parser.parse_args(argv)
    run_pipeline(args)
