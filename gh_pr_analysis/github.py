"""GitHub REST API: JSON requests, pagination, raw file bytes."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from gh_pr_analysis.config import API_VERSION

_MAX_TRANSIENT_RETRIES = 6


def _transient_backoff_sleep(attempt: int, url: str) -> None:
    delay = min(2.0 * (2**attempt), 120.0)
    short = url[:90] + "…" if len(url) > 90 else url
    print(
        f"Transient network error; sleeping {delay:.0f}s "
        f"(retry {attempt + 1}/{_MAX_TRANSIENT_RETRIES}) — {short}",
        file=sys.stderr,
    )
    time.sleep(delay)


def _header_get(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    v = headers.get(name)
    if v is None:
        v = headers.get(name.title())
    return v


def _is_rate_limit_error(code: int, detail: str, headers: Any) -> bool:
    if code == 429:
        return True
    if code != 403:
        return False
    if "rate limit" in detail.lower():
        return True
    rem = _header_get(headers, "X-RateLimit-Remaining")
    if rem is not None and rem.strip() == "0":
        return True
    return False


def _sleep_until_rate_limit_ok(headers: Any, url: str) -> None:
    """Wait until GitHub indicates we can retry (Retry-After or X-RateLimit-Reset)."""
    retry_after = _header_get(headers, "Retry-After")
    if retry_after:
        wait = float(retry_after)
    else:
        reset_s = _header_get(headers, "X-RateLimit-Reset")
        if reset_s is not None:
            try:
                wait = max(0.0, float(reset_s) - time.time()) + 1.0
            except ValueError:
                wait = 60.0
        else:
            wait = 60.0
    short = url if len(url) <= 100 else url[:100] + "…"
    print(
        f"GitHub rate limit; sleeping {wait:.0f}s then retrying … ({short})",
        file=sys.stderr,
    )
    time.sleep(wait)


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
    transient_failures = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                if stats is not None:
                    stats["github_rest"] = stats.get("github_rest", 0) + 1
                link = resp.headers.get("Link")
                body = resp.read().decode("utf-8")
                return json.loads(body), link
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if _is_rate_limit_error(e.code, detail, e.headers):
                transient_failures = 0
                _sleep_until_rate_limit_ok(e.headers, url)
                continue
            raise SystemExit(f"HTTP {e.code} for {url}\n{detail}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            transient_failures += 1
            if transient_failures >= _MAX_TRANSIENT_RETRIES:
                raise SystemExit(
                    f"GitHub request failed after {_MAX_TRANSIENT_RETRIES} retries: {url}\n{e}"
                ) from e
            _transient_backoff_sleep(transient_failures - 1, url)


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
    transient_failures = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                if stats is not None:
                    stats["raw_fetches"] = stats.get("raw_fetches", 0) + 1
                return resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if _is_rate_limit_error(e.code, detail, e.headers):
                transient_failures = 0
                _sleep_until_rate_limit_ok(e.headers, url)
                continue
            raise SystemExit(f"HTTP {e.code} for {url}\n{detail}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            transient_failures += 1
            if transient_failures >= _MAX_TRANSIENT_RETRIES:
                raise SystemExit(
                    f"GitHub request failed after {_MAX_TRANSIENT_RETRIES} retries: {url}\n{e}"
                ) from e
            _transient_backoff_sleep(transient_failures - 1, url)


def api_usage_dict(stats: dict[str, int]) -> dict[str, int]:
    gr = int(stats.get("github_rest", 0))
    rw = int(stats.get("raw_fetches", 0))
    return {
        "github_rest_requests": gr,
        "raw_file_fetches": rw,
        "http_total": gr + rw,
    }
