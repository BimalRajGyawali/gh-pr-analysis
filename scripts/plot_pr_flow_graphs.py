#!/usr/bin/env python3
"""
Render directed root-flow diagrams per PR from analyzed snapshots.

A flow is the forward reachable set from a root (changed symbol with in-degree 0 in
the changed-symbol directed call graph). Flows can overlap.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gh_pr_analysis.plots.pr_graph_viz import (
    PR_GRAPH_ARROW_PROPS,
    PR_GRAPH_Z_EDGE,
    PR_GRAPH_Z_LABEL,
    PR_GRAPH_Z_SCATTER,
)

from analyze_all_repos_connectivity import (
    build_changed_edges,
    discover_bundles,
    gather_changed_nodes,
    parse_repo_label,
    pr_snapshots_dir_for_reading,
    safe_load_json,
)

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Plot per-PR root flow graphs.")
    p.add_argument("--repos-root", type=Path, default=_ROOT / "repos_analysed")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=_ROOT / "viz_output_all_repos" / "graphs" / "flows",
    )
    p.add_argument("--limit-repos", type=int, default=None)
    p.add_argument("--limit-prs", type=int, default=None)
    p.add_argument("--max-flows", type=int, default=12)
    p.add_argument("--max-nodes-per-flow", type=int, default=80)
    p.add_argument(
        "--include-singleton-roots",
        action="store_true",
        help="Also draw single-node flows.",
    )
    return p


def roots_and_adjacency(
    nodes: set[str], directed: set[tuple[str, str]]
) -> tuple[list[str], dict[str, set[str]]]:
    out_adj: dict[str, set[str]] = {n: set() for n in nodes}
    in_deg: dict[str, int] = {n: 0 for n in nodes}
    for a, b in directed:
        if a not in out_adj or b not in out_adj:
            continue
        out_adj[a].add(b)
        in_deg[b] += 1
    roots = sorted([n for n in nodes if in_deg[n] == 0])
    return roots, out_adj


def reachable(start: str, out_adj: dict[str, set[str]]) -> set[str]:
    seen: set[str] = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for v in out_adj[u]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return seen


def circular_layout(nodes: list[str], radius: float = 0.88) -> dict[str, tuple[float, float]]:
    if len(nodes) == 1:
        return {nodes[0]: (0.0, 0.0)}
    out: dict[str, tuple[float, float]] = {}
    for i, n in enumerate(nodes):
        th = 2.0 * math.pi * (i / len(nodes))
        out[n] = (radius * math.cos(th), radius * math.sin(th))
    return out


def draw_pr_flows(
    repo: str,
    pr_number: int,
    directed_edges: set[tuple[str, str]],
    root_flows: list[tuple[str, set[str]]],
    out_path: Path,
    max_nodes_per_flow: int,
) -> None:
    if not root_flows:
        return

    panel_count = len(root_flows)
    cols = max(1, int(math.ceil(math.sqrt(panel_count))))
    rows = int(math.ceil(panel_count / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.9 * rows))
    axes_flat = list(axes.flat) if hasattr(axes, "flat") else [axes]

    for i, (root, node_set) in enumerate(root_flows):
        ax = axes_flat[i]
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        ax.set_aspect("equal", adjustable="box")

        nodes = sorted(node_set)[:max_nodes_per_flow]
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
                    arrowprops=dict(PR_GRAPH_ARROW_PROPS),
                    zorder=PR_GRAPH_Z_EDGE,
                    clip_on=False,
                )

        xs = [pos[n][0] for n in nodes]
        ys = [pos[n][1] for n in nodes]
        colors = ["#d62728" if n == root else "#1f77b4" for n in nodes]
        ax.scatter(
            xs,
            ys,
            s=28,
            c=colors,
            edgecolors="white",
            linewidths=0.4,
            zorder=PR_GRAPH_Z_SCATTER,
        )

        for n in nodes:
            x, y = pos[n]
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
                zorder=PR_GRAPH_Z_LABEL,
            )

        root_label = root.split("::", 1)[-1]
        title = f"Flow {i+1}: {len(node_set)} nodes\nroot={root_label}"
        if len(node_set) > len(nodes):
            title += f" (show {len(nodes)})"
        ax.set_title(title, fontsize=9)

    for j in range(panel_count, len(axes_flat)):
        axes_flat[j].axis("off")

    fig.suptitle(
        f"{repo} PR #{pr_number} — root flows\nflows={len(root_flows)}, edges={len(directed_edges)}",
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
        repo = parse_repo_label(bundle)
        repo_slug = repo.replace("/", "__")
        pr_root = pr_snapshots_dir_for_reading(bundle)
        snaps = sorted(pr_root.glob("pr_*/snapshot.json"))

        for sp in snaps:
            if args.limit_prs is not None and done >= args.limit_prs:
                print(f"Wrote {done} PR flow plots under {out_root}")
                return
            snap = safe_load_json(sp)
            if snap is None:
                continue

            nodes_map = gather_changed_nodes(snap, sp.parent)
            node_keys = set(nodes_map.keys())
            if not node_keys:
                continue
            directed = build_changed_edges(snap, sp.parent, nodes_map)
            if not directed:
                continue

            roots, out_adj = roots_and_adjacency(node_keys, directed)
            flows: list[tuple[str, set[str]]] = []
            for r in roots:
                rs = reachable(r, out_adj)
                if len(rs) >= 2 or args.include_singleton_roots:
                    flows.append((r, rs))
            flows.sort(key=lambda x: len(x[1]), reverse=True)
            flows = flows[: args.max_flows]
            if not flows:
                continue

            part = sp.parent.name
            pr_num = int(part[3:]) if part.startswith("pr_") and part[3:].isdigit() else -1
            out_path = out_root / repo_slug / f"pr_{pr_num}__flows.png"
            draw_pr_flows(
                repo,
                pr_num,
                directed,
                flows,
                out_path,
                args.max_nodes_per_flow,
            )
            done += 1

        print(f"[{bi}/{len(bundles)}] {repo} done", flush=True)

    print(f"Wrote {done} PR flow plots under {out_root}")


if __name__ == "__main__":
    main()
