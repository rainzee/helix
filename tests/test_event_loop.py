"""
Test: Event Loop — call_soon throughput.
Verifies the Qt-backed loop can schedule and execute callbacks at high rate.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from test_ui import PerfTestWindow, run_test


async def test_event_loop(window: PerfTestWindow) -> None:
    loop = asyncio.get_event_loop()
    window.log("[TEST] Measuring call_soon throughput...")

    total_executed = 0
    batch_size = 100
    iteration = 0

    while True:
        executed_this_batch = 0
        done_event = asyncio.Event()

        def _on_done():
            nonlocal executed_this_batch
            executed_this_batch += 1
            if executed_this_batch >= batch_size:
                done_event.set()

        for _ in range(batch_size):
            loop.call_soon(_on_done)

        await done_event.wait()
        total_executed += executed_this_batch
        iteration += 1

        if iteration % 10 == 0:
            window.log(
                f"[LOOP] Iteration {iteration} | "
                f"total_callbacks={total_executed}"
            )

        await asyncio.sleep(0.05)


if __name__ == "__main__":
    run_test(test_event_loop, duration=6.0, title="Event Loop Throughput")
