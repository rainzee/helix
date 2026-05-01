"""
Test: Task — creation and stepping throughput.
Spawns many short-lived tasks and measures completion rate.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from test_ui import PerfTestWindow, run_test


async def _short_task(task_id: int) -> int:
    """A minimal async task that yields a few times."""
    total = 0
    for i in range(3):
        await asyncio.sleep(0)
        total += i
    return total


async def test_tasks(window: PerfTestWindow) -> None:
    window.log("[TEST] Spawning short-lived tasks in waves...")

    wave = 0
    tasks_per_wave = 50
    total_completed = 0
    t0 = time.perf_counter()

    while True:
        wave += 1
        tasks = [
            asyncio.create_task(_short_task(wave * tasks_per_wave + i))
            for i in range(tasks_per_wave)
        ]

        results = await asyncio.gather(*tasks)
        total_completed += len(results)

        elapsed = time.perf_counter() - t0
        rate = total_completed / elapsed if elapsed > 0 else 0

        window.log(
            f"[TASK] Wave {wave} | "
            f"completed={total_completed} | "
            f"rate={rate:.0f} tasks/s"
        )

        await asyncio.sleep(0.1)


if __name__ == "__main__":
    run_test(test_tasks, duration=6.0, title="Task Throughput")
