from __future__ import annotations

import asyncio
import asyncio.events
import heapq
import socket
import sys
import threading
from selectors import BaseSelector, SelectorKey
from typing import override

from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QSocketNotifier,
    QTimer,
)


class PlaceholderSelector(BaseSelector):
    """A no-op selector. We use QSocketNotifier for I/O, not select()."""

    @override
    def register(self, fileobj, events, data=None) -> SelectorKey:
        return SelectorKey(fileobj, 0, events, data)

    @override
    def unregister(self, fileobj) -> SelectorKey:
        return SelectorKey(fileobj, 0, 0, None)

    @override
    def select(self, timeout: float | None = None) -> list:
        return []

    @override
    def get_map(self) -> dict:
        return {}


class QtEventLoop(asyncio.SelectorEventLoop):
    """
    A thin Qt-backed asyncio event loop.

    Qt's event dispatcher is the master. A zero-interval QTimer pumps
    asyncio's internal _ready and _scheduled queues. I/O readiness is
    delivered via QSocketNotifier, converted into standard asyncio handles.

    All of asyncio's C-accelerated Future, Task, and Handle machinery
    is preserved — we only replace the bottom-most scheduling layer.
    """

    def __init__(self, app: QCoreApplication):
        self._app = app

        # I/O tracking — must be initialized before super().__init__()
        # because _make_self_pipe() calls _add_reader() during init.
        self._notifiers: dict[tuple, QSocketNotifier] = {}

        # Batch size for ready queue drain per pump cycle
        self._batch_size = 64

        # Use the null selector — I/O goes through QSocketNotifier
        super().__init__(selector=PlaceholderSelector())

        self._timer = QTimer()
        self._timer.setInterval(0)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._pump)

        self._thread_id: int | None = None
        self._qt_loop: QEventLoop | None = None

    # ------------------------------------------------------------------
    # Override: run_forever / stop
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        self._check_closed()
        self._check_running()
        self._set_coroutine_origin_tracking(self._debug)
        self._thread_id = threading.get_ident()

        old_agen_hooks = sys.get_asyncgen_hooks()
        try:
            asyncio.events._set_running_loop(self)
            self._timer.start()
            # Each run_forever() gets its own QEventLoop — supports
            # nested run_until_complete calls during shutdown.
            qt_loop = QEventLoop(self._app)
            self._qt_loop = qt_loop
            qt_loop.exec()
        finally:
            self._qt_loop = None
            self._timer.stop()
            self._thread_id = None
            asyncio.events._set_running_loop(None)
            self._set_coroutine_origin_tracking(False)
            sys.set_asyncgen_hooks(*old_agen_hooks)

    def stop(self) -> None:
        """Stop the event loop. Safe to call from callbacks."""
        self.call_soon(self._do_stop)

    def _do_stop(self):
        if self._qt_loop is not None:
            self._qt_loop.quit()

    def is_running(self) -> bool:
        return self._thread_id is not None

    # ------------------------------------------------------------------
    # The pump: bridges Qt's event dispatch into asyncio's scheduling
    # ------------------------------------------------------------------

    def _pump(self) -> None:
        """
        Drain asyncio's internal queues. Called by QTimer at each
        Qt event loop iteration (interval=0).
        """
        # 1. Move due scheduled callbacks to _ready
        now = self.time()
        scheduled = self._scheduled
        ready = self._ready
        while scheduled:
            handle = scheduled[0]
            if handle._when > now:
                break
            heapq.heappop(scheduled)
            handle._scheduled = False
            if not handle._cancelled:
                ready.append(handle)

        # 2. Execute ready callbacks in batches
        batch = self._batch_size
        n = 0
        while ready and n < batch:
            handle = ready.popleft()
            if not handle._cancelled:
                handle._run()
            n += 1

        # 3. Adjust timer based on queue state
        if ready:
            # More work pending — keep timer at 0 (immediate)
            if self._timer.interval() != 0:
                self._timer.setInterval(0)
        elif scheduled:
            # Sleep until next scheduled callback
            delay_ms = max(1, int((scheduled[0]._when - self.time()) * 1000))
            self._timer.setInterval(delay_ms)
        else:
            # Nothing to do — stop the timer, will restart on call_soon
            self._timer.stop()

    # ------------------------------------------------------------------
    # Override call_soon to ensure the pump timer is running
    # ------------------------------------------------------------------

    def call_soon(self, callback, *args, context=None):
        handle = super().call_soon(callback, *args, context=context)
        if not self._timer.isActive():
            self._timer.setInterval(0)
            self._timer.start()
        return handle

    def call_soon_threadsafe(self, callback, *args, context=None):
        handle = super().call_soon_threadsafe(callback, *args, context=context)
        # super() already writes to self-pipe which triggers our QSocketNotifier
        # for the self-pipe reader fd — that will restart the pump timer via
        # _on_io_ready. No additional wakeup needed.
        return handle

    def call_later(self, delay, callback, *args, context=None):
        handle = super().call_later(delay, callback, *args, context=context)
        if not self._timer.isActive():
            delay_ms = max(1, int(delay * 1000))
            self._timer.setInterval(delay_ms)
            self._timer.start()
        return handle

    # ------------------------------------------------------------------
    # I/O: QSocketNotifier replaces selector.select()
    # ------------------------------------------------------------------

    def _add_reader(self, fd, callback, *args):
        if isinstance(fd, socket.socket):
            fd = fd.fileno()
        self._remove_reader(fd)
        notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read)
        notifier.activated.connect(lambda: self._on_io_ready(fd, callback, args))
        notifier.setEnabled(True)
        self._notifiers[("r", fd)] = notifier

    def _remove_reader(self, fd):
        if isinstance(fd, socket.socket):
            fd = fd.fileno()
        key = ("r", fd)
        notifier = self._notifiers.pop(key, None)
        if notifier is not None:
            notifier.setEnabled(False)
            notifier.deleteLater()
            return True
        return False

    def _add_writer(self, fd, callback, *args):
        if isinstance(fd, socket.socket):
            fd = fd.fileno()
        self._remove_writer(fd)
        notifier = QSocketNotifier(fd, QSocketNotifier.Type.Write)
        notifier.activated.connect(lambda: self._on_io_ready(fd, callback, args))
        notifier.setEnabled(True)
        self._notifiers[("w", fd)] = notifier

    def _remove_writer(self, fd):
        if isinstance(fd, socket.socket):
            fd = fd.fileno()
        key = ("w", fd)
        notifier = self._notifiers.pop(key, None)
        if notifier is not None:
            notifier.setEnabled(False)
            notifier.deleteLater()
            return True
        return False

    def _on_io_ready(self, fd, callback, args):
        """Execute an I/O callback directly (not enqueued).

        QSocketNotifier is level-triggered: it fires as long as the fd
        is readable/writable. We must consume the data synchronously
        to prevent infinite re-firing.
        """
        callback(*args)
        # Ensure the pump runs to process any handles scheduled by the callback
        if self._ready:
            self._timer.setInterval(0)
            if not self._timer.isActive():
                self._timer.start()

    @override
    def close(self) -> None:

        if self.is_running():
            raise RuntimeError("Cannot close a running event loop")

        if self.is_closed():
            return

        self._timer.stop()

        for notifier in self._notifiers.values():
            notifier.setEnabled(False)

        self._notifiers.clear()
        super().close()
