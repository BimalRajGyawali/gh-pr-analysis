"""Drawing defaults for per-PR call-graph figures (flows and connected components)."""

from __future__ import annotations

from typing import Any

# shrinkA/shrinkB (points): shorten arrows at each end so heads sit outside text boxes.
PR_GRAPH_ARROW_PROPS: dict[str, Any] = {
    "arrowstyle": "-|>",
    "lw": 0.7,
    "color": "#9e9e9e",
    "alpha": 0.75,
    "shrinkA": 26,
    "shrinkB": 26,
    "mutation_scale": 7,
}

# Edges below markers and labels so arrow shafts pass under nodes but heads stay clear of labels.
PR_GRAPH_Z_EDGE = 2
PR_GRAPH_Z_SCATTER = 3
PR_GRAPH_Z_LABEL = 4
