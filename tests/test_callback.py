"""
Test: Callback Performance

Tests call_soon and call_later callback scheduling and execution timing.
Measures per-callback overhead and total throughput.
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


async def test_callbacks(window: PerfTestWindow) -> None:
    loop = asyncio.get_event_loop()
    window.log("[TEST] Measuring callback scheduling and execution...")

    round_num = 0
    call_soon_count = 60
    call_later_count = 20

    while True:
        round_num += 1

        # Schedule call_soon callbacks
        results = []
        for i in range(call_soon_count):
            loop.call_soon(results.append, i)

        # Schedule call_later callbacks with small delays
        for i in range(call_later_count):
            loop.call_later(0.01 * (i + 1), results.append, i + call_soon_count)

        # Give time for all callbacks to execute
        await asyncio.sleep(0.3)

        avg_cb_us = (
            metrics.total_callback_time_us / metrics.callbacks_executed
            if metrics.callbacks_executed > 0
            else 0
        )

        window.log(
            f"[CALLBACK] Round {round_num} | "
            f"scheduled={metrics.callbacks_scheduled} | "
            f"executed={metrics.callbacks_executed} | "
            f"avg_cb={avg_cb_us:.1f}μs | "
            f"total_cb_time={metrics.total_callback_time_us}μs"
        )

        await asyncio.sleep(0.1)


if __name__ == "__main__":
    run_test(test_callbacks, duration=6.0, title="Callback Performance")
