import subprocess
import sys
from asyncio import SelectorEventLoop, SubprocessTransport
from asyncio.transports import ReadTransport, WriteTransport
from selectors import BaseSelector, SelectorKey
from socket import socket
from typing import TYPE_CHECKING, override

from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QProcess,
    QSocketNotifier,
    QTimer,
)

if TYPE_CHECKING:
    from asyncio import TimerHandle
    from asyncio.events import Handle
    from collections.abc import Callable
    from contextvars import Context


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


class _StdinWriteTransport(WriteTransport):
    """Write transport that forwards to QProcess stdin."""

    def __init__(self, loop, qproc, protocol, fd):
        super().__init__()
        self._loop = loop
        self._qproc = qproc
        self._protocol = protocol
        self._fd = fd
        self._closing = False

    def write(self, data):
        if self._closing:
            return
        self._qproc.write(data)

    def write_eof(self):
        self.close()

    def can_write_eof(self):
        return True

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._qproc.closeWriteChannel()
        self._loop.call_soon(self._protocol.pipe_connection_lost, self._fd, None)

    def is_closing(self):
        return self._closing

    def get_extra_info(self, name, default=None):
        return default


class _ReadPipeTransport(ReadTransport):
    """Read transport for a QProcess stdout/stderr channel."""

    def __init__(self):
        super().__init__()
        self._closing = False
        self._paused = False

    def is_reading(self):
        return not self._paused and not self._closing

    def pause_reading(self):
        self._paused = True

    def resume_reading(self):
        self._paused = False

    def close(self):
        self._closing = True

    def is_closing(self):
        return self._closing

    def get_extra_info(self, name, default=None):
        return default


class _QProcessTransport(SubprocessTransport):
    """Subprocess transport backed by QProcess — fully event-driven, no threads."""

    def __init__(
        self,
        loop,
        protocol,
        args,
        shell,
        stdin,
        stdout,
        stderr,
        bufsize,
        waiter=None,
        extra=None,
        **kwargs,
    ):
        super().__init__(extra)
        self._loop = loop
        self._protocol = protocol
        self._returncode = None
        self._exit_waiters = []
        self._pipes = {}
        self._closed = False

        self._qproc = QProcess()

        # Wire QProcess signals
        self._qproc.readyReadStandardOutput.connect(self._on_stdout)
        self._qproc.readyReadStandardError.connect(self._on_stderr)
        self._qproc.finished.connect(self._on_finished)

        # Determine program and arguments
        if shell:
            cmd = args if isinstance(args, str) else subprocess.list2cmdline(args)
            if sys.platform == "win32":
                program = "cmd.exe"
                self._qproc.setProgram(program)
                self._qproc.setNativeArguments(f"/c {cmd}")
            else:
                program = "/bin/sh"
                proc_args = ["-c", cmd]
                self._qproc.setProgram(program)
                self._qproc.setArguments(proc_args)
        else:
            arg_list = list(args) if not isinstance(args, str) else [args]
            program = arg_list[0]
            proc_args = arg_list[1:]
            self._qproc.setProgram(program)
            self._qproc.setArguments(proc_args)

        # Create pipe transports based on requested channels
        if stdin == subprocess.PIPE:
            self._pipes[0] = _StdinWriteTransport(loop, self._qproc, protocol, 0)

        if stdout == subprocess.PIPE:
            self._pipes[1] = _ReadPipeTransport()

        if stderr == subprocess.PIPE:
            self._pipes[2] = _ReadPipeTransport()

        # Start the process
        self._qproc.start()
        self._qproc.waitForStarted()
        self._pid = self._qproc.processId()

        # Notify protocol
        loop.call_soon(protocol.connection_made, self)

        # Resolve creation waiter
        if waiter is not None:
            loop.call_soon(waiter.set_result, None)

    def _on_stdout(self):
        data = self._qproc.readAllStandardOutput().data()
        if data:
            self._protocol.pipe_data_received(1, bytes(data))

    def _on_stderr(self):
        data = self._qproc.readAllStandardError().data()
        if data:
            self._protocol.pipe_data_received(2, bytes(data))

    def _on_finished(self, exit_code, _exit_status):
        self._returncode = exit_code

        # Drain any remaining data
        remaining_out = self._qproc.readAllStandardOutput().data()
        if remaining_out:
            self._protocol.pipe_data_received(1, bytes(remaining_out))

        remaining_err = self._qproc.readAllStandardError().data()
        if remaining_err:
            self._protocol.pipe_data_received(2, bytes(remaining_err))

        # Close read pipes
        if 1 in self._pipes:
            self._protocol.pipe_connection_lost(1, None)
        if 2 in self._pipes:
            self._protocol.pipe_connection_lost(2, None)

        self._protocol.process_exited()

        for waiter in self._exit_waiters:
            if not waiter.cancelled():
                waiter.set_result(exit_code)
        self._exit_waiters.clear()

    # --- SubprocessTransport interface ---

    def get_pid(self):
        return self._pid

    def get_returncode(self):
        return self._returncode

    def get_pipe_transport(self, fd):
        return self._pipes.get(fd)

    def send_signal(self, signal):
        self._qproc.kill()

    def terminate(self):
        self._qproc.terminate()

    def kill(self):
        self._qproc.kill()

    def close(self):
        if self._closed:
            return
        self._closed = True
        for pipe_t in self._pipes.values():
            pipe_t.close()
        if self._returncode is None:
            self._qproc.kill()

    async def _wait(self):
        if self._returncode is not None:
            return self._returncode
        waiter = self._loop.create_future()
        self._exit_waiters.append(waiter)
        return await waiter


class QtEventLoop(SelectorEventLoop):
    """
    A thin Qt-backed asyncio event loop.

    Qt's event dispatcher is the master. A zero-interval QTimer pumps
    asyncio's internal _ready and _scheduled queues. I/O readiness is
    delivered via QSocketNotifier, converted into standard asyncio handles.

    All of asyncio's C-accelerated Future, Task, and Handle machinery
    is preserved — we only replace the bottom-most scheduling layer.
    """

    def __init__(self, app: QCoreApplication) -> None:
        self._app = app
        self._notifiers: dict[tuple, QSocketNotifier] = {}

        super().__init__(selector=PlaceholderSelector())

        self._timer = QTimer()
        self._timer.setInterval(0)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._pump)

        self._thread_id: int | None = None
        self._qt_loop: QEventLoop | None = None

    @override
    def run_forever(self) -> None:
        self._run_forever_setup()  # type: ignore

        try:
            self._timer.start()
            qt_loop = QEventLoop(self._app)
            self._qt_loop = qt_loop
            qt_loop.exec()
        finally:
            self._qt_loop = None
            self._timer.stop()
            self._run_forever_cleanup()  # type: ignore

    @override
    def call_soon(
        self, callback: "Callable", *args, context: "Context | None" = None
    ) -> "Handle":
        """Override Asyncio's event loop call_soon to ensure the pump timer is active."""

        handle = super().call_soon(callback, *args, context=context)
        if not self._timer.isActive():
            self._timer.setInterval(0)
            self._timer.start()
        return handle

    @override
    def call_later(
        self,
        delay: float,
        callback: "Callable",
        *args,
        context: "Context | None" = None,
    ) -> "TimerHandle":
        """Override Asyncio's event loop call_later to ensure the pump timer is active."""

        handle = super().call_later(delay, callback, *args, context=context)
        if not self._timer.isActive():
            delay_ms = max(1, int(delay * 1000))
            self._timer.setInterval(delay_ms)
            self._timer.start()
        return handle

    @override
    def stop(self) -> None:
        self.call_soon(self._do_stop)

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

    async def _make_subprocess_transport(
        self,
        protocol,
        args,
        shell,
        stdin,
        stdout,
        stderr,
        bufsize,
        extra=None,
        **kwargs,
    ):
        """Create a subprocess transport backed by QProcess."""
        waiter = self.create_future()
        transport = _QProcessTransport(
            self,
            protocol,
            args,
            shell,
            stdin,
            stdout,
            stderr,
            bufsize,
            waiter=waiter,
            extra=extra,
            **kwargs,
        )
        try:
            await waiter
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException:
            transport.close()
            raise
        return transport

    def _pump(self) -> None:
        """
        Drain asyncio's internal queues. Called by QTimer at each
        Qt event loop iteration (interval=0).
        """

        super()._run_once()  # type: ignore

        if self._ready:  # type: ignore
            if self._timer.interval() != 0:
                self._timer.setInterval(0)
        elif self._scheduled:  # type: ignore
            delay_ms = max(1, int((self._scheduled[0]._when - self.time()) * 1000))  # type: ignore
            self._timer.setInterval(delay_ms)
        else:
            self._timer.stop()

    def _do_stop(self) -> None:
        if self._qt_loop is not None:
            self._qt_loop.quit()

    def _add_reader(self, fd: int, callback: "Callable", *args) -> None:
        """Add a file descriptor for read events using QSocketNotifier."""

        if isinstance(fd, socket):
            fd = fd.fileno()

        self._remove_reader(fd)
        notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read)
        notifier.activated.connect(lambda: self._on_io_ready(fd, callback, args))
        notifier.setEnabled(True)
        self._notifiers[("r", fd)] = notifier

    def _remove_reader(self, fd: int) -> bool:
        """Remove a file descriptor from read events."""

        if isinstance(fd, socket):
            fd = fd.fileno()

        key = ("r", fd)
        notifier = self._notifiers.pop(key, None)

        if notifier is not None:
            notifier.setEnabled(False)
            notifier.deleteLater()
            return True

        return False

    def _add_writer(self, fd: int, callback: "Callable", *args) -> None:
        """Add a file descriptor for write events using QSocketNotifier."""

        if isinstance(fd, socket):
            fd = fd.fileno()

        self._remove_writer(fd)
        notifier = QSocketNotifier(fd, QSocketNotifier.Type.Write)
        notifier.activated.connect(lambda: self._on_io_ready(fd, callback, args))
        notifier.setEnabled(True)
        self._notifiers[("w", fd)] = notifier

    def _remove_writer(self, fd: int) -> bool:
        """Remove a file descriptor from write events."""

        if isinstance(fd, socket):
            fd = fd.fileno()

        key = ("w", fd)
        notifier = self._notifiers.pop(key, None)

        if notifier is not None:
            notifier.setEnabled(False)
            notifier.deleteLater()
            return True

        return False

    def _on_io_ready(self, fd: int, callback: "Callable", args) -> None:
        """Execute an I/O callback directly (not enqueued).

        QSocketNotifier is level-triggered: it fires as long as the fd
        is readable/writable. We must consume the data synchronously
        to prevent infinite re-firing.
        """

        callback(*args)
        # Ensure the pump runs to process any handles scheduled by the callback
        if self._ready:  # type: ignore
            self._timer.setInterval(0)
            if not self._timer.isActive():
                self._timer.start()
