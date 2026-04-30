from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from .events import (
    QAsyncioEventLoop,
    QAsyncioEventLoopPolicy,
    QAsyncioHandle,
    QAsyncioTimerHandle,
)
from .futures import QAsyncioFuture
from .logging import _ENABLED as _PERF_ENABLED, _now_us, log_event, metrics
from .tasks import QAsyncioTask

__all__ = [
    "QAsyncioEventLoopPolicy",
    "QAsyncioEventLoop",
    "QAsyncioHandle",
    "QAsyncioTimerHandle",
    "QAsyncioFuture",
    "QAsyncioTask",
    "metrics",
]


def run(
    coro: Coroutine | None = None,
    keep_running: bool = True,
    quit_qapp: bool = True,
    *,
    handle_sigint: bool = False,
    debug: bool | None = None,
) -> Any:
    """
    Run the QtAsyncio event loop.

    If there is no instance of a QCoreApplication, QGuiApplication or
    QApplication yet, a new instance of QCoreApplication is created.

    :param coro:            The coroutine to run. Optional if keep_running is
                            True.
    :param keep_running:    If True, QtAsyncio (the asyncio event loop) will
                            continue running after the coroutine finished, or
                            run "forever" if no coroutine was provided.
                            If False, QtAsyncio will stop after the
                            coroutine finished. A coroutine must be provided if
                            this argument is set to False.
    :param quit_qapp:       If True, the QCoreApplication will quit when
                            QtAsyncio (the asyncio event loop) stops.
                            If False, the QCoreApplication will remain active
                            after QtAsyncio stops, and can continue to be used.
    :param handle_sigint:   If True, the SIGINT signal will be handled by the
                            event loop, causing it to stop.
    :param debug:           If True, the event loop will run in debug mode.
                            If False, the event loop will run in normal mode.
                            If None, the default behavior is used.
    """

    # Event loop policies are expected to be deprecated with Python 3.13, with
    # subsequent removal in Python 3.15. At that point, part of the current
    # logic of the QAsyncioEventLoopPolicy constructor will have to be moved
    # here and/or to a loop factory class (to be provided as an argument to
    # asyncio.run()). In particular, this concerns the logic of setting up the
    # QCoreApplication and the SIGINT handler.
    #
    # More details:
    # https://discuss.python.org/t/removing-the-asyncio-policy-system-asyncio-set-event-loop-policy-in-python-3-15/37553  # noqa: E501
    default_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(
        QAsyncioEventLoopPolicy(quit_qapp=quit_qapp, handle_sigint=handle_sigint)
    )

    if _PERF_ENABLED:
        log_event(
            "helix.run.start",
            keep_running=keep_running,
            quit_qapp=quit_qapp,
            handle_sigint=handle_sigint,
            debug=debug,
        )
        _run_start = _now_us()

    ret = None
    exc = None

    if keep_running:
        if coro:
            asyncio.ensure_future(coro)
        asyncio.get_event_loop().run_forever()
    else:
        if coro:
            ret = asyncio.run(coro, debug=debug)
        else:
            exc = RuntimeError(
                "QtAsyncio was set not to keep running after the coroutine "
                "finished, but no coroutine was provided."
            )

    asyncio.set_event_loop_policy(default_policy)

    if _PERF_ENABLED:
        _run_elapsed = _now_us() - _run_start  # type: ignore[possibly-undefined]
        log_event("helix.run.end", elapsed_us=_run_elapsed)
        metrics.log_summary()

    if ret:
        return ret
    if exc:
        raise exc
