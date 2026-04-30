"""
Performance tracking and logging for the Helix event loop library.

This module provides structured performance logging using loguru, gated behind
the HELIX_PERF_LOG environment variable. When enabled, it tracks:

- Event loop lifecycle (start, stop, close)
- Task creation, stepping, and completion with timing
- Future resolution timing
- Callback scheduling and execution timing
- Executor dispatch timing

Usage:
    Set HELIX_PERF_LOG=1 (or any truthy value) to enable performance logging.
    Set HELIX_PERF_LOG_LEVEL to control verbosity (default: DEBUG).
    Set HELIX_PERF_LOG_FILE to write logs to a file (default: stderr only).

All logging is no-op when disabled, imposing zero overhead on production use.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Generator

from loguru import logger

# --- Configuration ---

_ENABLED = bool(os.getenv("HELIX_PERF_LOG", ""))
_LOG_LEVEL = os.getenv("HELIX_PERF_LOG_LEVEL", "DEBUG").upper()
_LOG_FILE = os.getenv("HELIX_PERF_LOG_FILE", "")

# Configure loguru
# Remove default handler and set up performance-specific logging
logger.remove()

if _ENABLED:
    # Stderr handler with performance format
    logger.add(
        sink=lambda msg: __import__("sys").stderr.write(msg),
        level=_LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>helix.perf</cyan> | "
            "{message}"
        ),
        filter=lambda record: record["extra"].get("perf", False),
    )

    # Optional file handler
    if _LOG_FILE:
        logger.add(
            _LOG_FILE,
            level=_LOG_LEVEL,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "helix.perf | "
                "{message}"
            ),
            filter=lambda record: record["extra"].get("perf", False),
            rotation="10 MB",
            retention="7 days",
        )

# Bind the performance logger context
perf_logger = logger.bind(perf=True)


# --- Timing utilities ---


def _now_us() -> int:
    """Return current time in microseconds (monotonic clock)."""
    return time.perf_counter_ns() // 1000


@contextmanager
def track_duration(operation: str, **kwargs: Any) -> Generator[dict, None, None]:
    """
    Context manager that logs the duration of an operation.

    Args:
        operation: Name of the operation being tracked.
        **kwargs: Additional structured fields to include in the log.

    Yields:
        A dict where callers can store additional metadata (e.g., result info).
    """
    if not _ENABLED:
        yield {}
        return

    metadata: dict[str, Any] = {}
    start = _now_us()
    try:
        yield metadata
    finally:
        elapsed_us = _now_us() - start
        extra = {**kwargs, **metadata}
        extra_str = " | ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
        if extra_str:
            perf_logger.debug(f"{operation} | elapsed={elapsed_us}μs | {extra_str}")
        else:
            perf_logger.debug(f"{operation} | elapsed={elapsed_us}μs")


def log_event(operation: str, level: str = "DEBUG", **kwargs: Any) -> None:
    """
    Log a single performance event (no duration tracking).

    Args:
        operation: Name of the event.
        level: Log level (DEBUG, INFO, WARNING, etc.).
        **kwargs: Additional structured fields.
    """
    if not _ENABLED:
        return

    extra_str = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    msg = f"{operation} | {extra_str}" if extra_str else operation
    perf_logger.log(level, msg)


def track_call(operation: str, **static_kwargs: Any) -> Callable:
    """
    Decorator that logs the duration of a function/method call.

    Args:
        operation: Name for the operation in logs.
        **static_kwargs: Static fields always included in the log.
    """

    def decorator(func: Callable) -> Callable:
        if not _ENABLED:
            return func

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = _now_us()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed_us = _now_us() - start
                extra_str = (
                    " | ".join(f"{k}={v}" for k, v in static_kwargs.items())
                    if static_kwargs
                    else ""
                )
                if extra_str:
                    perf_logger.debug(
                        f"{operation} | elapsed={elapsed_us}μs | {extra_str}"
                    )
                else:
                    perf_logger.debug(f"{operation} | elapsed={elapsed_us}μs")

        return wrapper

    return decorator


# --- Metric counters (lightweight, always active when enabled) ---


class PerfMetrics:
    """
    Lightweight performance counters for aggregate metrics.
    These are accumulated in-process and can be queried or logged periodically.
    """

    __slots__ = (
        "tasks_created",
        "tasks_completed",
        "tasks_cancelled",
        "task_steps",
        "futures_created",
        "futures_resolved",
        "futures_cancelled",
        "callbacks_scheduled",
        "callbacks_executed",
        "executor_dispatches",
        "total_task_step_time_us",
        "total_callback_time_us",
    )

    def __init__(self) -> None:
        self.tasks_created: int = 0
        self.tasks_completed: int = 0
        self.tasks_cancelled: int = 0
        self.task_steps: int = 0
        self.futures_created: int = 0
        self.futures_resolved: int = 0
        self.futures_cancelled: int = 0
        self.callbacks_scheduled: int = 0
        self.callbacks_executed: int = 0
        self.executor_dispatches: int = 0
        self.total_task_step_time_us: int = 0
        self.total_callback_time_us: int = 0

    def summary(self) -> dict[str, int]:
        """Return all metrics as a dictionary."""
        return {slot: getattr(self, slot) for slot in self.__slots__}

    def log_summary(self) -> None:
        """Log the current metrics summary."""
        if not _ENABLED:
            return
        metrics = self.summary()
        lines = " | ".join(f"{k}={v}" for k, v in metrics.items())
        perf_logger.info(f"metrics_summary | {lines}")

    def reset(self) -> None:
        """Reset all counters to zero."""
        for slot in self.__slots__:
            setattr(self, slot, 0)


# Global metrics instance
metrics = PerfMetrics()

# Public API
__all__ = [
    "perf_logger",
    "track_duration",
    "track_call",
    "log_event",
    "metrics",
    "PerfMetrics",
]
