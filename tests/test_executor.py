"""
Test: Executor — run_in_executor dispatch.
Verifies blocking work can be offloaded to threads without blocking the loop.
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from test_ui import PerfTestWindow, run_test


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
    total_dispatched = 0
    t0 = time.perf_counter()

    while True:
        round_num += 1

        start = time.perf_counter()
        futs = [
            loop.run_in_executor(None, _blocking_work, 5000 + i * 1000)
            for i in range(dispatches_per_round)
        ]

        results = await asyncio.gather(*futs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        total_dispatched += dispatches_per_round

        total_elapsed = time.perf_counter() - t0
        rate = total_dispatched / total_elapsed if total_elapsed > 0 else 0

        window.log(
            f"[EXECUTOR] Round {round_num} | "
            f"time={elapsed_ms:.1f}ms | "
            f"total={total_dispatched} | "
            f"rate={rate:.1f}/s"
        )

        await asyncio.sleep(0.2)


if __name__ == "__main__":
    run_test(test_executor, duration=6.0, title="Executor Throughput")
