"""Wall-clock step timings using ``time.perf_counter`` (for stderr + JSON logs)."""

from __future__ import annotations

import time


def clock() -> float:
    return time.perf_counter()


def elapsed_ms(since: float) -> float:
    return round((time.perf_counter() - since) * 1000.0, 2)
