#!/usr/bin/env python3
"""
Compute PR-level connectivity metrics from already-fetched snapshots under repos_analysed/.

This script is intentionally post-processing only (no API usage). It reads snapshot.json
files, uses changed symbols recorded in python_fn_class_analysis, infers changed->changed
call edges from downloaded head files, and writes aggregate metrics for downstream plots.

Metrics:
  - Weakly connected components (undirected partition of the directed call graph among
    changed symbols): ``connected_component_*`` and ``cpr`` (connected-component
    participation ratio: nodes in multinode components / n_nodes).
  - Flows from roots (in-degree 0, forward callee edges only): ``forward_*``.
    ``forward_reach_coverage`` uses the union of multi-node root closures / n_nodes.
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gh_pr_analysis.paths import pr_snapshots_dir_for_reading


@dataclass(frozen=True)
class SymbolNode:
    key: str
    filename: str
    qname: str
    short_name: str
    class_name: str | None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Analyze connected components and root flows for changed Python functions/methods/classes "
            "from repos_analysed snapshots."
        )
    )
    p.add_argument(
        "--repos-root",
        type=Path,
        default=_ROOT / "repos_analysed",
        help="Root containing repo bundles with open_prs.json and snapshots/",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "viz_output_all_repos" / "connected_components" / "aggregate_pr_connectivity.json",
        help="Output JSON path.",
    )
    p.add_argument(
        "--limit-prs",
        type=int,
        default=None,
        help="Optional max number of PR snapshots to process (for quick tests).",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def discover_bundles(repos_root: Path) -> list[Path]:
    if not repos_root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(repos_root.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if (p / "open_prs.json").is_file():
            out.append(p)
    return out


def safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def parse_repo_label(bundle: Path) -> str:
    idx = safe_load_json(bundle / "open_prs.json")
    if isinstance(idx, dict):
        meta = idx.get("_meta")
        if isinstance(meta, dict):
            repo = meta.get("repo")
            if isinstance(repo, str) and repo.strip():
                return repo
    return bundle.name.replace("_", "/", 1)


def symbol_class_name(qname: str) -> str | None:
    parts = qname.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:-1])
    return None


def _callable_qnames_for_file(path: Path) -> set[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    out: set[str] = set()
    for qname, node, _class_name in iter_definitions(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(qname)
    return out


def gather_changed_nodes(snapshot: dict[str, Any], pr_dir: Path) -> dict[str, SymbolNode]:
    out: dict[str, SymbolNode] = {}
    pya = snapshot.get("python_fn_class_analysis")
    if not isinstance(pya, dict):
        return out
    per_file = pya.get("per_file")
    if not isinstance(per_file, list):
        return out

    files = snapshot.get("files")
    files_by_name: dict[str, dict[str, Any]] = {}
    if isinstance(files, list):
        for row in files:
            if isinstance(row, dict):
                fn = row.get("filename")
                if isinstance(fn, str):
                    files_by_name[fn] = row

    for row in per_file:
        if not isinstance(row, dict):
            continue
        fname = row.get("filename")
        names = row.get("modified_functions_and_classes")
        if not isinstance(fname, str) or not isinstance(names, list):
            continue
        callable_qnames: set[str] = set()
        fentry = files_by_name.get(fname)
        if isinstance(fentry, dict):
            local = fentry.get("local_path")
            if isinstance(local, str) and local:
                callable_qnames = _callable_qnames_for_file(pr_dir / local)
        for qname in names:
            if not isinstance(qname, str) or not qname.strip():
                continue
            qname = qname.strip()
            # Keep only callable symbols (functions/methods/nested functions), not class defs.
            if qname not in callable_qnames:
                continue
            key = f"{fname}::{qname}"
            short = qname.split(".")[-1]
            out[key] = SymbolNode(
                key=key,
                filename=fname,
                qname=qname,
                short_name=short,
                class_name=symbol_class_name(qname),
            )
    return out


def iter_definitions(tree: ast.AST) -> list[tuple[str, ast.AST, str | None]]:
    defs: list[tuple[str, ast.AST, str | None]] = []

    def walk(node: ast.AST, prefix: str, in_class: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qn = f"{prefix}.{child.name}" if prefix else child.name
                defs.append((qn, child, symbol_class_name(qn)))
                walk(child, qn, qn)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = f"{prefix}.{child.name}" if prefix else child.name
                defs.append((qn, child, in_class))
                walk(child, qn, in_class)
            else:
                walk(child, prefix, in_class)

    walk(tree, "", None)
    return defs


def call_tokens(func: ast.AST) -> list[str]:
    toks: list[str] = []
    for n in ast.walk(func):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Name):
            toks.append(f.id)
            continue
        if isinstance(f, ast.Attribute):
            toks.append(f.attr)
            if isinstance(f.value, ast.Name):
                toks.append(f"{f.value.id}.{f.attr}")
    return toks


def extract_calls_per_definition(source: str) -> dict[str, list[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, list[str]] = {}
    for qname, node, _class_name in iter_definitions(tree):
        out[qname] = call_tokens(node)
    return out


def build_lookup(nodes: dict[str, SymbolNode]) -> tuple[dict[str, list[str]], dict[str, str]]:
    by_short: dict[str, list[str]] = {}
    unique_by_file_qn: dict[str, str] = {}
    for key, node in nodes.items():
        by_short.setdefault(node.short_name, []).append(key)
        unique_by_file_qn[f"{node.filename}::{node.qname}"] = key
    return by_short, unique_by_file_qn


def resolve_targets(
    src: SymbolNode,
    token: str,
    by_short: dict[str, list[str]],
    by_file_qn: dict[str, str],
) -> set[str]:
    out: set[str] = set()
    if "." in token:
        # Handles common cases like "Class.method" and "self.method"/"cls.method".
        left, right = token.split(".", 1)
        if left in ("self", "cls") and src.class_name:
            k = by_file_qn.get(f"{src.filename}::{src.class_name}.{right}")
            if k:
                out.add(k)
            return out
        k = by_file_qn.get(f"{src.filename}::{token}")
        if k:
            out.add(k)
            return out
        token = right

    # Local class method preference for plain calls in methods.
    if src.class_name:
        k = by_file_qn.get(f"{src.filename}::{src.class_name}.{token}")
        if k:
            out.add(k)
            return out

    # Unique-by-short-name fallback across changed nodes (conservative).
    cands = by_short.get(token, [])
    if len(cands) == 1:
        out.add(cands[0])
    return out


def build_changed_edges(
    snapshot: dict[str, Any],
    pr_dir: Path,
    nodes: dict[str, SymbolNode],
) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    if not nodes:
        return edges

    files = snapshot.get("files")
    if not isinstance(files, list):
        return edges

    by_short, by_file_qn = build_lookup(nodes)
    files_by_name: dict[str, dict[str, Any]] = {}
    for f in files:
        if isinstance(f, dict):
            name = f.get("filename")
            if isinstance(name, str):
                files_by_name[name] = f

    calls_cache: dict[str, dict[str, list[str]]] = {}
    for node in nodes.values():
        if node.filename in calls_cache:
            continue
        fe = files_by_name.get(node.filename)
        if not isinstance(fe, dict):
            calls_cache[node.filename] = {}
            continue
        local = fe.get("local_path")
        if not isinstance(local, str) or not local:
            calls_cache[node.filename] = {}
            continue
        path = pr_dir / local
        if not path.is_file():
            calls_cache[node.filename] = {}
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            calls_cache[node.filename] = {}
            continue
        calls_cache[node.filename] = extract_calls_per_definition(source)

    for src_key, src in nodes.items():
        toks = calls_cache.get(src.filename, {}).get(src.qname, [])
        for tok in toks:
            for dst_key in resolve_targets(src, tok, by_short, by_file_qn):
                if dst_key == src_key:
                    continue
                edges.add((src_key, dst_key))
    return edges


def component_sizes(nodes: set[str], edges: set[tuple[str, str]]) -> list[int]:
    """Undirected connected component sizes (weakly connected on directed edges)."""
    if not nodes:
        return []
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        if a not in adj or b not in adj:
            continue
        adj[a].add(b)
        adj[b].add(a)

    seen: set[str] = set()
    sizes: list[int] = []
    for n in nodes:
        if n in seen:
            continue
        stack = [n]
        seen.add(n)
        size = 0
        while stack:
            cur = stack.pop()
            size += 1
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        sizes.append(size)
    sizes.sort(reverse=True)
    return sizes


def forward_flow_from_roots_metrics(
    node_keys: set[str],
    directed: set[tuple[str, str]],
) -> dict[str, Any]:
    """Roots = in-degree 0; each root's flow size = |forward reachable set| (including root)."""
    if not node_keys:
        return {
            "forward_root_count": 0,
            "forward_closure_sizes": [],
            "forward_flow_count_ge2": 0,
            "forward_multinode_closure_sizes": [],
            "largest_forward_multinode_closure_size": 0,
            "mean_forward_multinode_closure_size": None,
            "median_forward_multinode_closure_size": None,
            "forward_union_reachable_count": 0,
            "forward_union_reachable_count_ge2": 0,
            "forward_reach_coverage": None,
        }

    n_nodes = len(node_keys)
    out_adj: dict[str, set[str]] = {n: set() for n in node_keys}
    in_deg: dict[str, int] = {n: 0 for n in node_keys}
    for a, b in directed:
        if a not in out_adj or b not in out_adj:
            continue
        out_adj[a].add(b)
        in_deg[b] += 1

    def reachable_set(start: str) -> set[str]:
        seen: set[str] = {start}
        stack = [start]
        while stack:
            u = stack.pop()
            for v in out_adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        return seen

    roots = [n for n in node_keys if in_deg[n] == 0]
    union_reachable: set[str] = set()
    union_reachable_multinode: set[str] = set()
    closure_sizes: list[int] = []
    for r in roots:
        rset = reachable_set(r)
        union_reachable |= rset
        sz = len(rset)
        closure_sizes.append(sz)
        if sz >= 2:
            union_reachable_multinode |= rset
    closure_sizes.sort(reverse=True)
    multinode = [s for s in closure_sizes if s >= 2]

    if multinode:
        mean_m = statistics.mean(multinode)
        median_m = statistics.median(multinode)
    else:
        mean_m = None
        median_m = None

    largest_m = max(multinode) if multinode else 0

    return {
        "forward_root_count": len(roots),
        "forward_closure_sizes": closure_sizes,
        "forward_flow_count_ge2": len(multinode),
        "forward_multinode_closure_sizes": multinode,
        "largest_forward_multinode_closure_size": largest_m,
        "mean_forward_multinode_closure_size": mean_m,
        "median_forward_multinode_closure_size": median_m,
        "forward_union_reachable_count": len(union_reachable),
        "forward_union_reachable_count_ge2": len(union_reachable_multinode),
        "forward_reach_coverage": len(union_reachable_multinode) / n_nodes,
    }


def summarize_pr(
    repo: str,
    pr_number: int,
    snapshot: dict[str, Any],
    pr_dir: Path,
) -> dict[str, Any]:
    nodes_map = gather_changed_nodes(snapshot, pr_dir)
    node_keys = set(nodes_map.keys())
    directed = build_changed_edges(snapshot, pr_dir, nodes_map)
    undirected = {tuple(sorted((a, b))) for a, b in directed if a != b}
    n_nodes = len(node_keys)

    comps = component_sizes(node_keys, directed)
    multinode_cc = [s for s in comps if s >= 2]
    nodes_in_multinode_cc = sum(multinode_cc)
    cpr = None if n_nodes == 0 else nodes_in_multinode_cc / n_nodes
    if multinode_cc:
        mean_cc_m = statistics.mean(multinode_cc)
        median_cc_m = statistics.median(multinode_cc)
    else:
        mean_cc_m = None
        median_cc_m = None
    largest_cc_partition = comps[0] if comps else 0

    forward = forward_flow_from_roots_metrics(node_keys, directed)

    return {
        "repo": repo,
        "pr_number": pr_number,
        "n_nodes": n_nodes,
        "n_edges_directed": len(directed),
        "n_edges_undirected": len(undirected),
        "connected_component_sizes": multinode_cc,
        "connected_component_count": len(multinode_cc),
        "nodes_in_multinode_connected_components": nodes_in_multinode_cc,
        "cpr": cpr,
        "largest_connected_component_partition_size": largest_cc_partition,
        "largest_connected_component_size": max(multinode_cc) if multinode_cc else 0,
        "mean_multinode_connected_component_size": mean_cc_m,
        "median_multinode_connected_component_size": median_cc_m,
        **forward,
    }


def process_bundle(
    bundle: Path,
    *,
    limit_left: int | None,
    verbose: bool,
) -> tuple[list[dict[str, Any]], int]:
    repo = parse_repo_label(bundle)
    root = pr_snapshots_dir_for_reading(bundle)
    paths = sorted(root.glob("pr_*/snapshot.json"))
    rows: list[dict[str, Any]] = []
    consumed = 0

    for sp in paths:
        if limit_left is not None and consumed >= limit_left:
            break
        raw = safe_load_json(sp)
        if raw is None:
            continue
        meta = raw.get("_meta")
        pr_num = None
        if isinstance(meta, dict):
            pn = meta.get("pull_number")
            if isinstance(pn, int):
                pr_num = pn
        if pr_num is None:
            # Fallback to folder name pr_<n>.
            part = sp.parent.name
            if part.startswith("pr_"):
                try:
                    pr_num = int(part[3:])
                except ValueError:
                    pr_num = -1
            else:
                pr_num = -1

        row = summarize_pr(repo, pr_num, raw, sp.parent)
        rows.append(row)
        consumed += 1
        if verbose and consumed % 100 == 0:
            print(f"  {repo}: processed {consumed} PRs …", file=sys.stderr, flush=True)
    return rows, consumed


def main() -> None:
    args = build_parser().parse_args()
    repos_root = args.repos_root.resolve()
    out = args.out.resolve()

    bundles = discover_bundles(repos_root)
    if not bundles:
        raise SystemExit(f"No bundles found under {repos_root}")

    per_pr: list[dict[str, Any]] = []
    bundle_rows: list[dict[str, Any]] = []
    remaining = args.limit_prs

    for i, bundle in enumerate(bundles, start=1):
        if remaining is not None and remaining <= 0:
            break
        repo = parse_repo_label(bundle)
        print(f"[{i}/{len(bundles)}] {repo}", file=sys.stderr, flush=True)
        rows, used = process_bundle(bundle, limit_left=remaining, verbose=args.verbose)
        per_pr.extend(rows)
        bundle_rows.append({"dir": bundle.name, "repo": repo, "prs_processed": used})
        if remaining is not None:
            remaining -= used

    coverages = [
        r["forward_reach_coverage"]
        for r in per_pr
        if isinstance(r.get("forward_reach_coverage"), (int, float))
    ]
    cprs = [r["cpr"] for r in per_pr if isinstance(r.get("cpr"), (int, float))]
    payload: dict[str, Any] = {
        "_meta": {
            "schema_version": 7,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repos_root": str(repos_root),
            "bundle_count": len(bundle_rows),
            "pr_count": len(per_pr),
            "note": (
                "Induced changed-symbol directed call graph "
                "(functions and class/nested methods from python_fn_class_analysis; class defs excluded via AST). "
                "Connected components: undirected (weakly connected) partition; "
                "connected_component_sizes lists component sizes >=2 only; "
                "connected_component_count = len(that list); "
                "cpr (connected-component participation ratio) = nodes in multinode components / n_nodes; "
                "largest_connected_component_size = max multinode component size (0 if none); "
                "largest_connected_component_partition_size = largest component in full partition (singletons included). "
                "Flows: forward_root_count = changed nodes with no incoming call from another changed node; "
                "forward_closure_sizes = sorted sizes of forward reachable sets from each root (including the root); "
                "forward_flow_count_ge2 counts roots whose forward closure has size>=2; "
                "forward_multinode_closure_sizes lists those sizes (>=2) only; "
                "forward_reach_coverage = |union of multi-node root closures| / n_nodes. "
                "Flows may overlap and are not a partition."
            ),
        },
        "bundles": bundle_rows,
        "forward_reach_coverage_per_pr": coverages,
        "cpr_per_pr": cprs,
        "per_pr": per_pr,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out)
    print(f"Wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
