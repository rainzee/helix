"""
Test: Callback — call_soon and call_later scheduling and execution.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from test_ui import PerfTestWindow, run_test


async def test_callbacks(window: PerfTestWindow) -> None:
    loop = asyncio.get_event_loop()
    window.log("[TEST] Measuring callback scheduling...")

    round_num = 0
    call_soon_count = 60
    call_later_count = 20
    total_executed = 0
    t0 = time.perf_counter()

    while True:
        round_num += 1
        executed = 0

        # call_soon
        for i in range(call_soon_count):
            loop.call_soon(lambda: None)

        # call_later with small delays
        for i in range(call_later_count):
            loop.call_later(0.01 * (i + 1), lambda: None)

        # Give time for all callbacks to fire
        await asyncio.sleep(0.3)
        total_executed += call_soon_count + call_later_count

        elapsed = time.perf_counter() - t0
        rate = total_executed / elapsed if elapsed > 0 else 0

        window.log(
            f"[CALLBACK] Round {round_num} | "
            f"total={total_executed} | "
            f"rate={rate:.0f}/s"
        )

        await asyncio.sleep(0.1)


if __name__ == "__main__":
    run_test(test_callbacks, duration=6.0, title="Callback Throughput")
