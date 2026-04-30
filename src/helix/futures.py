from __future__ import annotations

import asyncio
import contextvars
import enum
from typing import Any, Callable

from . import events


class QAsyncioFuture:
    """https://docs.python.org/3/library/asyncio-future.html"""

    # Declare that this class implements the Future protocol. The field must
    # exist and be boolean - True indicates 'await' or 'yield from', False
    # indicates 'yield'.
    _asyncio_future_blocking = False

    # Integer state constants for fast comparison (avoid enum overhead in hot paths)
    _STATE_PENDING = 0
    _STATE_CANCELLED = 1
    _STATE_DONE_WITH_RESULT = 2
    _STATE_DONE_WITH_EXCEPTION = 3

    # Keep the enum class for backward compatibility
    class FutureState(enum.Enum):
        PENDING = enum.auto()
        CANCELLED = enum.auto()
        DONE_WITH_RESULT = enum.auto()
        DONE_WITH_EXCEPTION = enum.auto()

    def __init__(
        self,
        *,
        loop: "events.QAsyncioEventLoop | None" = None,
        context: contextvars.Context | None = None,
    ) -> None:
        self._loop: "events.QAsyncioEventLoop"
        if loop is None:
            self._loop = asyncio.events.get_event_loop()  # type: ignore[assignment]
        else:
            self._loop = loop
        self._context = context

        self._state = QAsyncioFuture._STATE_PENDING
        self._result: Any = None
        self._exception: BaseException | None = None

        self._cancel_message: str | None = None

        # List of callbacks that are called when the future is done.
        self._callbacks: list[Callable] = []

    def __await__(self):
        if not self.done():
            self._asyncio_future_blocking = True
            yield self
            if not self.done():
                raise RuntimeError(
                    "await was not used with a Future or Future-like object"
                )
        return self.result()

    __iter__ = __await__

    def _schedule_callbacks(self, context: contextvars.Context | None = None):
        """A future can optionally have callbacks that are called when the future is done."""
        callbacks = self._callbacks
        if not callbacks:
            return
        ctx = context if context else self._context
        loop_call_soon = self._loop.call_soon
        for cb in callbacks:
            loop_call_soon(cb, self, context=ctx)

    def result(self) -> Any | Exception:
        state = self._state
        if state == QAsyncioFuture._STATE_DONE_WITH_RESULT:
            return self._result
        if state == QAsyncioFuture._STATE_DONE_WITH_EXCEPTION and self._exception:
            raise self._exception
        if state == QAsyncioFuture._STATE_CANCELLED:
            if self._cancel_message:
                raise asyncio.CancelledError(self._cancel_message)
            else:
                raise asyncio.CancelledError
        raise asyncio.InvalidStateError

    def set_result(self, result: Any) -> None:
        self._result = result
        self._state = QAsyncioFuture._STATE_DONE_WITH_RESULT
        self._schedule_callbacks()

    def set_exception(self, exception: Exception) -> None:
        self._exception = exception
        self._state = QAsyncioFuture._STATE_DONE_WITH_EXCEPTION
        self._schedule_callbacks()

    def done(self) -> bool:
        return self._state != QAsyncioFuture._STATE_PENDING

    def cancelled(self) -> bool:
        return self._state == QAsyncioFuture._STATE_CANCELLED

    def add_done_callback(
        self, cb: Callable, *, context: contextvars.Context | None = None
    ) -> None:
        if self.done():
            self._loop.call_soon(
                cb, self, context=context if context else self._context
            )
        else:
            self._callbacks.append(cb)

    def remove_done_callback(self, cb: Callable) -> int:
        original_len = len(self._callbacks)
        self._callbacks = [_cb for _cb in self._callbacks if _cb != cb]
        return original_len - len(self._callbacks)

    def cancel(self, msg: str | None = None) -> bool:
        if self.done():
            return False
        self._state = QAsyncioFuture._STATE_CANCELLED
        self._cancel_message = msg
        self._schedule_callbacks()
        return True

    def exception(self) -> BaseException | None:
        if self._state == QAsyncioFuture._STATE_CANCELLED:
            raise asyncio.CancelledError
        if self.done():
            return self._exception
        raise asyncio.InvalidStateError

    def get_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop
