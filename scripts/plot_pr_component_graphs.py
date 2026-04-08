#!/usr/bin/env python3
"""
Render connected-component node/edge diagrams per PR from analyzed snapshots.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SymbolNode:
    key: str
    filename: str
    qname: str
    short_name: str
    class_name: str | None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Plot connected components per PR.")
    p.add_argument("--repos-root", type=Path, default=_ROOT / "repos_analysed")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=_ROOT / "viz_output_all_repos" / "pr_component_graphs",
    )
    p.add_argument("--limit-repos", type=int, default=None)
    p.add_argument("--limit-prs", type=int, default=None)
    p.add_argument("--max-components", type=int, default=12)
    p.add_argument("--max-nodes-per-component", type=int, default=80)
    return p


def safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        x = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return x if isinstance(x, dict) else None


def parse_repo(bundle: Path) -> str:
    idx = safe_load_json(bundle / "open_prs.json")
    if isinstance(idx, dict):
        meta = idx.get("_meta")
        if isinstance(meta, dict) and isinstance(meta.get("repo"), str):
            return meta["repo"]
    return bundle.name.replace("_", "/", 1)


def discover_bundles(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / "open_prs.json").is_file():
            out.append(p)
    return out


def symbol_class_name(qname: str) -> str | None:
    parts = qname.split(".")
    return ".".join(parts[:-1]) if len(parts) >= 2 else None


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
    for qname, node in iter_defs(tree):
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
        for f in files:
            if isinstance(f, dict):
                fn = f.get("filename")
                if isinstance(fn, str):
                    files_by_name[fn] = f
    for row in per_file:
        if not isinstance(row, dict):
            continue
        filename = row.get("filename")
        names = row.get("modified_functions_and_classes")
        if not isinstance(filename, str) or not isinstance(names, list):
            continue
        callable_qnames: set[str] = set()
        fentry = files_by_name.get(filename)
        if isinstance(fentry, dict):
            local = fentry.get("local_path")
            if isinstance(local, str) and local:
                callable_qnames = _callable_qnames_for_file(pr_dir / local)
        for qname in names:
            if not isinstance(qname, str) or not qname:
                continue
            if qname not in callable_qnames:
                continue
            key = f"{filename}::{qname}"
            out[key] = SymbolNode(
                key=key,
                filename=filename,
                qname=qname,
                short_name=qname.split(".")[-1],
                class_name=symbol_class_name(qname),
            )
    return out


def iter_defs(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    out: list[tuple[str, ast.AST]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                q = f"{prefix}.{child.name}" if prefix else child.name
                out.append((q, child))
                walk(child, q)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}.{child.name}" if prefix else child.name
                out.append((q, child))
                walk(child, q)
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def call_tokens(node: ast.AST) -> list[str]:
    toks: list[str] = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Name):
            toks.append(f.id)
        elif isinstance(f, ast.Attribute):
            toks.append(f.attr)
            if isinstance(f.value, ast.Name):
                toks.append(f"{f.value.id}.{f.attr}")
    return toks


def extract_calls_per_def(source: str) -> dict[str, list[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, list[str]] = {}
    for qname, node in iter_defs(tree):
        out[qname] = call_tokens(node)
    return out


def build_lookup(nodes: dict[str, SymbolNode]) -> tuple[dict[str, list[str]], dict[str, str]]:
    by_short: dict[str, list[str]] = {}
    by_file_qname: dict[str, str] = {}
    for k, n in nodes.items():
        by_short.setdefault(n.short_name, []).append(k)
        by_file_qname[f"{n.filename}::{n.qname}"] = k
    return by_short, by_file_qname


def resolve_targets(src: SymbolNode, token: str, by_short: dict[str, list[str]], by_file_qname: dict[str, str]) -> set[str]:
    out: set[str] = set()
    if "." in token:
        left, right = token.split(".", 1)
        if left in ("self", "cls") and src.class_name:
            k = by_file_qname.get(f"{src.filename}::{src.class_name}.{right}")
            if k:
                out.add(k)
            return out
        k = by_file_qname.get(f"{src.filename}::{token}")
        if k:
            out.add(k)
            return out
        token = right
    if src.class_name:
        k = by_file_qname.get(f"{src.filename}::{src.class_name}.{token}")
        if k:
            out.add(k)
            return out
    cands = by_short.get(token, [])
    if len(cands) == 1:
        out.add(cands[0])
    return out


def changed_edges(snapshot: dict[str, Any], pr_dir: Path, nodes: dict[str, SymbolNode]) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    files = snapshot.get("files")
    if not isinstance(files, list) or not nodes:
        return edges
    by_short, by_file_q = build_lookup(nodes)

    files_by_name: dict[str, dict[str, Any]] = {}
    for f in files:
        if isinstance(f, dict) and isinstance(f.get("filename"), str):
            files_by_name[f["filename"]] = f

    calls_cache: dict[str, dict[str, list[str]]] = {}
    for n in nodes.values():
        if n.filename in calls_cache:
            continue
        fe = files_by_name.get(n.filename)
        if not isinstance(fe, dict):
            calls_cache[n.filename] = {}
            continue
        lp = fe.get("local_path")
        if not isinstance(lp, str):
            calls_cache[n.filename] = {}
            continue
        path = pr_dir / lp
        if not path.is_file():
            calls_cache[n.filename] = {}
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            calls_cache[n.filename] = {}
            continue
        calls_cache[n.filename] = extract_calls_per_def(source)

    for a_key, a in nodes.items():
        toks = calls_cache.get(a.filename, {}).get(a.qname, [])
        for t in toks:
            for b_key in resolve_targets(a, t, by_short, by_file_q):
                if a_key != b_key:
                    edges.add((a_key, b_key))
    return edges


def components(nodes: set[str], undirected_edges: set[tuple[str, str]]) -> list[list[str]]:
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in undirected_edges:
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)
    seen: set[str] = set()
    out: list[list[str]] = []
    for n in nodes:
        if n in seen:
            continue
        st = [n]
        seen.add(n)
        comp: list[str] = []
        while st:
            cur = st.pop()
            comp.append(cur)
            for nx in adj[cur]:
                if nx not in seen:
                    seen.add(nx)
                    st.append(nx)
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def circular_layout(nodes: list[str], radius: float = 0.88) -> dict[str, tuple[float, float]]:
    if len(nodes) == 1:
        return {nodes[0]: (0.0, 0.0)}
    out: dict[str, tuple[float, float]] = {}
    for i, n in enumerate(nodes):
        th = 2.0 * math.pi * (i / len(nodes))
        out[n] = (radius * math.cos(th), radius * math.sin(th))
    return out


def draw_pr(
    repo: str,
    pr_number: int,
    node_set: set[str],
    directed_edges: set[tuple[str, str]],
    undirected_edges: set[tuple[str, str]],
    out_path: Path,
    max_components: int,
    max_nodes_per_component: int,
) -> None:
    comps = components(node_set, undirected_edges)
    connected = [c for c in comps if len(c) >= 2][:max_components]
    singletons = [c[0] for c in comps if len(c) == 1]
    panel_count = len(connected) + (1 if singletons else 0)
    if panel_count == 0:
        return

    cols = max(1, int(math.ceil(math.sqrt(panel_count))))
    rows = int(math.ceil(panel_count / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.1 * cols, 3.8 * rows))
    axes_flat = list(axes.flat) if hasattr(axes, "flat") else [axes]

    for i, comp in enumerate(connected):
        ax = axes_flat[i]
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        ax.set_aspect("equal", adjustable="box")

        nodes = sorted(comp)[:max_nodes_per_component]
        pos = circular_layout(nodes)
        local = set(nodes)
        for a, b in directed_edges:
            if a in local and b in local:
                xa, ya = pos[a]
                xb, yb = pos[b]
                ax.annotate(
                    "",
                    xy=(xb, yb),
                    xytext=(xa, ya),
                    arrowprops={
                        "arrowstyle": "-|>",
                        "lw": 0.7,
                        "color": "#9e9e9e",
                        "alpha": 0.75,
                        "shrinkA": 8,
                        "shrinkB": 8,
                        "mutation_scale": 8,
                    },
                    zorder=1,
                )
        xs = [pos[n][0] for n in nodes]
        ys = [pos[n][1] for n in nodes]
        ax.scatter(xs, ys, s=24, c="#1f77b4", edgecolors="white", linewidths=0.4)
        for n in nodes:
            x, y = pos[n]
            # Label with short symbol name for readability.
            label = n.split("::", 1)[-1].split(".")[-1]
            ax.text(
                x,
                y,
                label,
                fontsize=6.5,
                ha="center",
                va="center",
                color="#111111",
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": "white",
                    "edgecolor": "#dddddd",
                    "alpha": 0.8,
                },
                zorder=3,
            )
        title = f"C{i+1}: {len(comp)}"
        if len(comp) > len(nodes):
            title += f" (show {len(nodes)})"
        ax.set_title(title)

    if singletons:
        ax = axes_flat[len(connected)]
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        ax.set_aspect("equal", adjustable="box")
        show = singletons[:max_nodes_per_component]
        pos = circular_layout(show, radius=0.75) if show else {}
        xs = [pos[n][0] for n in show]
        ys = [pos[n][1] for n in show]
        ax.scatter(xs, ys, s=28, c="#bdbdbd", marker="x", linewidths=1.0)
        ttl = f"Singletons: {len(singletons)}"
        if len(singletons) > len(show):
            ttl += f" (show {len(show)})"
        ax.set_title(ttl)
        ax.text(0.5, -0.08, "Not connected components", transform=ax.transAxes, ha="center", va="top", fontsize=8, color="#666666")

    for j in range(panel_count, len(axes_flat)):
        axes_flat[j].axis("off")

    fig.suptitle(
        f"{repo} PR #{pr_number} — connected components\nnodes={len(node_set)}, edges={len(undirected_edges)}",
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def main() -> None:
    args = build_parser().parse_args()
    bundles = discover_bundles(args.repos_root.resolve())
    if args.limit_repos is not None:
        bundles = bundles[: args.limit_repos]

    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    done = 0

    for bi, bundle in enumerate(bundles, start=1):
        repo = parse_repo(bundle)
        repo_slug = repo.replace("/", "__")
        pr_root = bundle / "snapshots"
        if not pr_root.is_dir():
            pr_root = bundle
        snaps = sorted(pr_root.glob("pr_*/snapshot.json"))
        for sp in snaps:
            if args.limit_prs is not None and done >= args.limit_prs:
                print(f"Wrote {done} PR plots under {out_root}")
                return
            snap = safe_load_json(sp)
            if snap is None:
                continue
            nodes_map = gather_changed_nodes(snap, sp.parent)
            node_set = set(nodes_map.keys())
            if not node_set:
                continue
            d_edges = changed_edges(snap, sp.parent, nodes_map)
            u_edges = {tuple(sorted((a, b))) for a, b in d_edges if a != b}
            if not u_edges:
                # Still draw a singleton panel so user can see no connectivity.
                pass
            part = sp.parent.name
            pr_num = int(part[3:]) if part.startswith("pr_") and part[3:].isdigit() else -1
            out_path = out_root / repo_slug / f"pr_{pr_num}__components.png"
            draw_pr(
                repo,
                pr_num,
                node_set,
                d_edges,
                u_edges,
                out_path,
                args.max_components,
                args.max_nodes_per_component,
            )
            done += 1
        print(f"[{bi}/{len(bundles)}] {repo} done", flush=True)

    print(f"Wrote {done} PR plots under {out_root}")


if __name__ == "__main__":
    main()
