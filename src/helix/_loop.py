import heapq
import sys
import threading
from asyncio import SelectorEventLoop, TimerHandle
from asyncio.events import Handle, _set_running_loop
from collections import deque
from collections.abc import Callable
from contextvars import Context
from selectors import BaseSelector, SelectorKey
from socket import socket
from typing import override

from PySide6.QtCore import QCoreApplication, QEventLoop, QSocketNotifier, QTimer


class PlaceholderSelector(BaseSelector):
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


class HelixEventLoop(SelectorEventLoop):
    """事件循环"""

    def __init__(self, app: QCoreApplication) -> None:
        self._batch_size = 64
        self._app = app
        self._notifiers: dict[tuple[str, int], QSocketNotifier] = {}

        super().__init__(selector=PlaceholderSelector())

        self._timer = QTimer()
        self._timer.setInterval(0)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self.pump)

        self._thread_id: int | None = None
        self._loop: QEventLoop | None = None

    def pump(self) -> None:
        now: float = self.time()
        ready: deque[TimerHandle] = self._ready  # type: ignore
        scheduled: list[TimerHandle] = self._scheduled  # type: ignore

        while scheduled:
            handle = scheduled[0]
            if handle._when > now:
                break

            heapq.heappop(scheduled)
            handle._scheduled = False

            if not handle._cancelled:
                ready.append(handle)

        batch = self._batch_size
        n = 0
        while ready and n < batch:
            handle = ready.popleft()
            if not handle._cancelled:
                handle._run()
            n += 1

        if ready:
            if self._timer.interval() != 0:
                self._timer.setInterval(0)
        elif scheduled:
            delay_ms = max(1, int((scheduled[0]._when - self.time()) * 1000))
            self._timer.setInterval(delay_ms)
        else:
            self._timer.stop()

    def stop(self) -> None:
        self.call_soon(self._do_stop)

    def _do_stop(self) -> None:
        if self._loop is not None:
            self._loop.quit()

    @override
    def run_forever(self) -> None:
        self._check_closed()  # type: ignore
        self._check_running()  # type: ignore
        self._set_coroutine_origin_tracking(self._debug)  # type: ignore
        self._thread_id = threading.get_ident()
        old_agen_hooks = sys.get_asyncgen_hooks()

        try:
            _set_running_loop(self)
            self._timer.start()
            loop = QEventLoop(self._app)
            self._loop = loop
            loop.exec()
        finally:
            self._loop = None
            self._timer.stop()
            self._thread_id = None
            sys.set_asyncgen_hooks(None)
            self._set_coroutine_origin_tracking(False)  # type: ignore
            sys.set_asyncgen_hooks(*old_agen_hooks)

    @override
    def is_running(self) -> bool:
        return self._thread_id is not None

    @override
    def call_soon(
        self,
        callback: Callable,
        *args,
        context: Context | None = None,
    ) -> Handle:
        handle = super().call_soon(callback, *args, context=context)
        if not self._timer.isActive():
            self._timer.setInterval(0)
            self._timer.start()
        return handle

    @override
    def call_soon_threadsafe(
        self,
        callback: Callable,
        *args,
        context: Context | None = None,
    ) -> Handle:
        return super().call_soon_threadsafe(callback, *args, context=context)

    @override
    def call_later(
        self, delay: float, callback: Callable, *args, context: Context | None = None
    ) -> TimerHandle:
        handle = super().call_later(delay, callback, *args, context=context)
        if not self._timer.isActive():
            delay_ms = max(1, int(delay * 1000))
            self._timer.setInterval(delay_ms)
            self._timer.start()
        return handle

    def _add_reader(self, fd: int, callback: Callable, *args) -> None:
        if isinstance(fd, socket):
            fd = fd.fileno()

        self.remove_reader(fd)
        notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read)
        notifier.activated.connect(lambda: self.on_io_ready(fd, callback, args))
        notifier.setEnabled(True)
        self._notifiers[("r", fd)] = notifier

    def _remove_reader(self, fd: int) -> bool:
        if isinstance(fd, socket):
            fd = fd.fileno()

        key = ("r", fd)
        notifier = self._notifiers.pop(key, None)

        if notifier is not None:
            notifier.setEnabled(False)
            notifier.deleteLater()
            return True

        return False

    def _add_writer(self, fd: int, callback: Callable, *args) -> None:
        if isinstance(fd, socket):
            fd = fd.fileno()

        self._remove_writer(fd)
        notifier = QSocketNotifier(fd, QSocketNotifier.Type.Write)
        notifier.activated.connect(lambda: self.on_io_ready(fd, callback, args))
        notifier.setEnabled(True)
        self._notifiers[("w", fd)] = notifier

    def _remove_writer(self, fd: int) -> bool:
        if isinstance(fd, socket):
            fd = fd.fileno()

        key = ("w", fd)
        notifier = self._notifiers.pop(key, None)

        if notifier is not None:
            notifier.setEnabled(False)
            notifier.deleteLater()
            return True

        return False

    def on_io_ready(self, fd: int, callback: Callable, *args) -> None:
        callback(*args)
        if self._ready:  # type: ignore
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
