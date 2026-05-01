import asyncio
from typing import Any, Coroutine

from PySide6.QtCore import QCoreApplication

from .loop import QtEventLoop

__all__ = ["run", "QtEventLoop"]


def run(
    coro: Coroutine | None = None,
    *,
    keep_running: bool = True,
    app: QCoreApplication,
    quit_qapp: bool = True,
) -> Any:
    """
    Run an async coroutine on a Qt-backed event loop.

    Args:
        coro:         The coroutine to run. Optional if keep_running=True.
        keep_running: If True, the loop keeps running after the coro finishes
                      (useful for GUI apps). If False, stops when coro completes.
        app:          The QApplication instance (required).
        quit_qapp:    If True, quit the QApplication when the loop stops.

    Returns:
        The coroutine's return value (if keep_running=False and coro provided).

    Example:
        from PySide6.QtWidgets import QApplication

        app = QApplication([])

        # GUI app — loop keeps running until window is closed
        helix.run(app=app)

        # Run a coroutine and get its result
        result = helix.run(fetch_data(), app=app, keep_running=False)
    """

    loop = QtEventLoop(app)

    asyncio.set_event_loop(loop)

    try:
        if keep_running:
            if coro is not None:
                loop.create_task(coro)
            loop.run_forever()
            return None
        else:
            if coro is None:
                raise RuntimeError("A coroutine is required when keep_running=False")
            return loop.run_until_complete(coro)
    finally:
        try:
            _cancel_all_tasks(loop)
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
            if quit_qapp:
                app.quit()


def _cancel_all_tasks(loop: asyncio.AbstractEventLoop) -> None:
    to_cancel = asyncio.all_tasks(loop)
    if not to_cancel:
        return
    for task in to_cancel:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*to_cancel, return_exceptions=True))
    for task in to_cancel:
        if task.cancelled():
            continue
        if task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "unhandled exception during shutdown",
                    "exception": task.exception(),
                    "task": task,
                }
            )
