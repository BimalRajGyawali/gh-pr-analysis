"""Unified-diff line mapping and AST span analysis for .py files in PRs."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

from gh_pr_analysis.timing_log import clock, elapsed_ms

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def patch_head_touched_lines(patch: str | None) -> set[int]:
    """
    Line numbers in the PR head file touched by the diff: every '+' line, and
    each '-' line maps to the current head line index (handles deletions).
    """
    if not patch:
        return set()
    touched: set[int] = set()
    for m in _HUNK_HEADER_RE.finditer(patch):
        new_line = int(m.group(3))
        start = m.end()
        nxt = _HUNK_HEADER_RE.search(patch, start)
        end = nxt.start() if nxt else len(patch)
        block = patch[start:end]
        for raw in block.splitlines():
            if not raw or raw.startswith("\\"):
                continue
            op = raw[0]
            if op == "+":
                touched.add(new_line)
                new_line += 1
            elif op == " ":
                new_line += 1
            elif op == "-":
                touched.add(new_line)
    return touched


def iter_py_def_class_spans(tree: ast.AST) -> list[tuple[int, int, str]]:
    """(start_line, end_line, qualified_name) for FunctionDef, AsyncFunctionDef, ClassDef."""
    out: list[tuple[int, int, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qn = f"{prefix}.{child.name}" if prefix else child.name
                end = getattr(child, "end_lineno", None) or child.lineno
                out.append((child.lineno, end, qn))
                visit(child, qn)
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def spans_intersect_touched(lo: int, hi: int, touched: set[int]) -> bool:
    if not touched:
        return False
    return any(lo <= ln <= hi for ln in touched)


def analyze_python_fn_class_changes(
    pr_dir: Path,
    files: list[dict[str, Any]],
    *,
    log_prefix: str | None = None,
) -> dict[str, Any]:
    """
    Count .py files where at least one function/class (AST span) intersects
    head-side lines implied by the unified diff patch + downloaded head file.
    """
    file_count = 0
    per_file: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    py_total = sum(1 for e in files if str(e.get("filename") or "").endswith(".py"))
    if log_prefix:
        print(
            f"  [{log_prefix}] analyzing {py_total} .py file(s) for fn/class ∩ diff …",
            file=sys.stderr,
            flush=True,
        )

    for entry in files:
        name = entry.get("filename") or ""
        if not name.endswith(".py"):
            continue
        t0 = clock()

        def done(msg: str) -> None:
            if log_prefix:
                print(
                    f"  [{log_prefix}] {name}: {msg} ({elapsed_ms(t0):.0f}ms)",
                    file=sys.stderr,
                    flush=True,
                )

        local = entry.get("local_path")
        if not local:
            skipped.append({"filename": name, "reason": "no_local_path"})
            done("skip — no local_path")
            continue
        fpath = pr_dir / local
        if not fpath.is_file():
            skipped.append({"filename": name, "reason": "missing_file"})
            done("skip — missing on disk")
            continue
        try:
            source = fpath.read_text(encoding="utf-8")
        except OSError as e:
            skipped.append({"filename": name, "reason": f"read_error:{e}"})
            done(f"skip — read_error: {e}")
            continue
        nlines = max(1, source.count("\n") + (0 if source.endswith("\n") else 1))
        patch = entry.get("patch")
        touched = patch_head_touched_lines(patch if isinstance(patch, str) else None)
        status = entry.get("status", "")
        if not touched and status == "added" and not patch:
            touched = set(range(1, nlines + 1))
        if not touched and not patch:
            skipped.append({"filename": name, "reason": "no_patch"})
            done("skip — no patch")
            continue
        if not touched:
            skipped.append({"filename": name, "reason": "empty_touch_set"})
            done("skip — empty touch set")
            continue
        try:
            tree = ast.parse(source, filename=name)
        except SyntaxError as e:
            skipped.append({"filename": name, "reason": f"syntax_error:{e}"})
            done(f"skip — syntax_error: {e}")
            continue
        spans = iter_py_def_class_spans(tree)
        hit_names = [qn for lo, hi, qn in spans if spans_intersect_touched(lo, hi, touched)]
        if hit_names:
            file_count += 1
            per_file.append(
                {
                    "filename": name,
                    "modified_functions_and_classes": hit_names,
                }
            )
            preview = ", ".join(hit_names[:4])
            if len(hit_names) > 4:
                preview += ", …"
            done(f"hit — {len(hit_names)} fn/class ({preview})")
        else:
            done("no fn/class intersects touched lines")

    if log_prefix:
        print(
            f"  [{log_prefix}] done — {file_count} file(s) with hits, "
            f"{len(skipped)} skipped, {py_total} .py seen",
            file=sys.stderr,
            flush=True,
        )

    return {
        "file_count": file_count,
        "per_file": per_file,
        "skipped": skipped,
        "note": (
            "Uses head file + patch: head line numbers from '+' and '-' hunks intersect "
            "ast lineno/end_lineno. No patch and not added-file → skipped. Requires Python 3.8+ end_lineno."
        ),
    }
