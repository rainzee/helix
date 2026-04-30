"""
Test: Future Performance

Tests future creation, resolution, and cancellation throughput.
Measures how quickly futures can be resolved and callbacks dispatched.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ["HELIX_PERF_LOG"] = "1"
os.environ["HELIX_PERF_LOG_LEVEL"] = "DEBUG"

from test_ui import PerfTestWindow, run_test

from helix.logging import metrics


async def test_futures(window: PerfTestWindow) -> None:
    loop = asyncio.get_event_loop()
    window.log("[TEST] Measuring future resolution throughput...")

    round_num = 0
    futures_per_round = 50

    while True:
        round_num += 1

        # Create and immediately resolve futures
        futs = []
        for i in range(futures_per_round):
            fut = loop.create_future()
            futs.append(fut)

        # Resolve half, cancel the other half
        for i, fut in enumerate(futs):
            if i % 2 == 0:
                fut.set_result(i)
            else:
                fut.cancel()

        # Await the resolved ones
        for i, fut in enumerate(futs):
            if i % 2 == 0:
                await fut

        window.log(
            f"[FUTURE] Round {round_num} | "
            f"created={metrics.futures_created} | "
            f"resolved={metrics.futures_resolved} | "
            f"cancelled={metrics.futures_cancelled}"
        )

        await asyncio.sleep(0.1)


if __name__ == "__main__":
    run_test(test_futures, duration=6.0, title="Future Performance")
