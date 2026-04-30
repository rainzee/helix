"""
Test: Task Performance

Tests task creation, stepping, and completion throughput.
Spawns many short-lived tasks and measures aggregate step timing.
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


async def _short_task(task_id: int) -> int:
    """A minimal async task that yields a few times then returns."""
    total = 0
    for i in range(3):
        await asyncio.sleep(0)
        total += i
    return total


async def test_tasks(window: PerfTestWindow) -> None:
    window.log("[TEST] Spawning short-lived tasks in waves...")

    wave = 0
    tasks_per_wave = 20

    while True:
        wave += 1
        tasks = [
            asyncio.ensure_future(_short_task(wave * tasks_per_wave + i))
            for i in range(tasks_per_wave)
        ]

        await asyncio.gather(*tasks)

        avg_step_us = (
            metrics.total_task_step_time_us / metrics.task_steps
            if metrics.task_steps > 0
            else 0
        )

        window.log(
            f"[TASK] Wave {wave} done | "
            f"created={metrics.tasks_created} | "
            f"completed={metrics.tasks_completed} | "
            f"steps={metrics.task_steps} | "
            f"avg_step={avg_step_us:.1f}μs"
        )

        await asyncio.sleep(0.1)


if __name__ == "__main__":
    run_test(test_tasks, duration=6.0, title="Task Performance")
