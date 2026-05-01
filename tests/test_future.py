"""
Test: Future — creation, resolution, cancellation.
Uses standard asyncio futures (C-accelerated) through the Qt loop.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from test_ui import PerfTestWindow, run_test


async def test_futures(window: PerfTestWindow) -> None:
    loop = asyncio.get_event_loop()
    window.log("[TEST] Measuring future resolution throughput...")

    round_num = 0
    futures_per_round = 100
    total_resolved = 0
    total_cancelled = 0
    t0 = time.perf_counter()

    while True:
        round_num += 1

        futs = [loop.create_future() for _ in range(futures_per_round)]

        # Resolve half, cancel the other half
        for i, fut in enumerate(futs):
            if i % 2 == 0:
                fut.set_result(i)
            else:
                fut.cancel()

        # Await the resolved ones
        for i, fut in enumerate(futs):
            if i % 2 == 0:
                result = await fut
                total_resolved += 1
            else:
                total_cancelled += 1

        elapsed = time.perf_counter() - t0
        rate = total_resolved / elapsed if elapsed > 0 else 0

        window.log(
            f"[FUTURE] Round {round_num} | "
            f"resolved={total_resolved} | "
            f"cancelled={total_cancelled} | "
            f"rate={rate:.0f}/s"
        )

        await asyncio.sleep(0.1)


if __name__ == "__main__":
    run_test(test_futures, duration=6.0, title="Future Throughput")
