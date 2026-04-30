"""
Test: Executor Performance

Tests run_in_executor dispatch — measures overhead of wrapping synchronous
functions into the QAsyncioExecutorWrapper and thread pool submission.
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
os.environ["HELIX_PERF_LOG"] = "1"
os.environ["HELIX_PERF_LOG_LEVEL"] = "DEBUG"

from test_ui import PerfTestWindow, run_test

from helix.logging import metrics


def _blocking_work(n: int) -> float:
    """Simulate a short blocking computation."""
    total = 0.0
    for i in range(n):
        total += math.sin(i)
    return total


async def test_executor(window: PerfTestWindow) -> None:
    loop = asyncio.get_event_loop()
    window.log("[TEST] Dispatching blocking work to executor...")

    round_num = 0
    dispatches_per_round = 5

    while True:
        round_num += 1

        start = time.perf_counter()
        futs = []
        for i in range(dispatches_per_round):
            fut = loop.run_in_executor(None, _blocking_work, 5000 + i * 1000)
            futs.append(fut)

        results = await asyncio.gather(*futs)
        elapsed_ms = (time.perf_counter() - start) * 1000

        window.log(
            f"[EXECUTOR] Round {round_num} | "
            f"dispatches={metrics.executor_dispatches} | "
            f"round_time={elapsed_ms:.1f}ms | "
            f"results={[f'{r:.2f}' for r in results]}"
        )

        await asyncio.sleep(0.2)


if __name__ == "__main__":
    run_test(test_executor, duration=6.0, title="Executor Performance")
