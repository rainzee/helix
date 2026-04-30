"""
Test: Event Loop Performance

Tests the helix event loop lifecycle — start, scheduling overhead, and stop.
Measures how many call_soon iterations can be processed per second.
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


async def test_event_loop(window: PerfTestWindow) -> None:
    loop = asyncio.get_event_loop()
    window.log("[TEST] Measuring call_soon throughput...")

    iteration = 0
    batch_size = 100

    while True:
        # Schedule a batch of no-op callbacks
        for _ in range(batch_size):
            loop.call_soon(lambda: None)

        iteration += 1
        if iteration % 10 == 0:
            window.log(
                f"[LOOP] Batch {iteration} | "
                f"callbacks_scheduled={metrics.callbacks_scheduled} | "
                f"callbacks_executed={metrics.callbacks_executed}"
            )

        # Yield to let the event loop process callbacks and render
        await asyncio.sleep(0.05)


if __name__ == "__main__":
    run_test(test_event_loop, duration=6.0, title="Event Loop Performance")
