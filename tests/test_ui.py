"""
Shared UI module for Helix performance tests.

Provides a reusable test harness with:
- An expanding/rotating triangle rendered via QPainter (OpenGL-free)
- A QTextEdit log panel in vertical layout
- Real-time FPS and state display in the window title
- Auto-close after a configurable duration
- A LogHandler that routes loguru output into the QTextEdit

Usage:
    from test_ui import PerfTestWindow, run_test

    async def my_test(window: PerfTestWindow):
        # your async test logic here
        window.log("doing stuff...")
        await asyncio.sleep(1)

    if __name__ == "__main__":
        run_test(my_test, duration=5.0, title="My Test")
"""

from __future__ import annotations

import asyncio
import math
import sys
import time
from typing import Awaitable, Callable

from PySide6.QtCore import QElapsedTimer, QPointF, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import helix
from helix.logging import metrics, perf_logger

# Type alias for the async test coroutine factory
TestCoroutine = Callable[["PerfTestWindow"], Awaitable[None]]


class TriangleWidget(QWidget):
    """
    A widget that renders a continuously expanding and rotating triangle.
    The triangle grows over time and rotates, providing a visual indicator
    that the event loop is running smoothly.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._frame_count = 0
        self._fps = 0.0
        self._last_fps_time = time.perf_counter()
        self._base_size = 20.0  # starting triangle radius
        self._max_size = 150.0
        self._growth_rate = 15.0  # pixels per second expansion
        self._rotation_speed = 90.0  # degrees per second
        self.setMinimumHeight(200)

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def paintEvent(self, event) -> None:  # noqa: N802
        self._frame_count += 1
        now = time.perf_counter()
        dt = now - self._last_fps_time
        if dt >= 1.0:
            self._fps = self._frame_count / dt if dt > 0 else 0
            self._frame_count = 0
            self._last_fps_time = now

        elapsed_sec = self._elapsed.elapsed() / 1000.0

        # Expanding size (cycles via modulo)
        cycle = elapsed_sec % 10.0  # 10-second growth cycle
        size = self._base_size + self._growth_rate * cycle
        size = min(size, self._max_size)

        # Rotation
        angle_deg = elapsed_sec * self._rotation_speed
        angle_rad = math.radians(angle_deg)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        # Compute triangle vertices
        points = QPolygonF()
        for i in range(3):
            a = angle_rad + i * (2.0 * math.pi / 3.0)
            px = cx + size * math.cos(a)
            py = cy + size * math.sin(a)
            points.append(QPointF(px, py))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Color shifts over time
        hue = int(elapsed_sec * 36) % 360
        color = QColor.fromHsv(hue, 200, 240)
        painter.setPen(QPen(color, 2))
        painter.setBrush(QBrush(color.lighter(150)))
        painter.drawPolygon(points)
        painter.end()


class PerfTestWindow(QWidget):
    """
    Main test window with vertical layout:
    - Top: animated triangle widget
    - Bottom: QTextEdit log panel

    Also displays FPS and metrics in the window title.
    """

    def __init__(
        self,
        title: str = "Helix Perf Test",
        duration: float = 5.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._duration = duration
        self._start_time = time.perf_counter()
        self._closed = False
        self._last_fps_log_time = time.perf_counter()

        self.setWindowTitle(title)
        self.resize(600, 500)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter()
        from PySide6.QtCore import Qt
        splitter.setOrientation(Qt.Orientation.Vertical)

        self._triangle = TriangleWidget()
        splitter.addWidget(self._triangle)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, monospace; font-size: 10pt; }"
        )
        splitter.addWidget(self._log_edit)

        splitter.setSizes([200, 300])
        layout.addWidget(splitter)

        # Refresh timer — drives animation and title updates
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(16)  # ~60 FPS target
        self._refresh_timer.timeout.connect(self._on_refresh)
        self._refresh_timer.start()

        # Install loguru sink that routes to QTextEdit
        self._sink_id = perf_logger.add(
            self._loguru_sink,
            level="DEBUG",
            format="{time:HH:mm:ss.SSS} | {level: <8} | {message}",
            filter=lambda record: record["extra"].get("perf", False),
        )

    @property
    def triangle(self) -> TriangleWidget:
        return self._triangle

    @property
    def log_edit(self) -> QTextEdit:
        return self._log_edit

    def log(self, message: str) -> None:
        """Append a message to the log panel."""
        self._log_edit.append(message)
        # Auto-scroll
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _loguru_sink(self, message) -> None:
        """Sink function for loguru — appends formatted message to QTextEdit."""
        text = str(message).rstrip("\n")
        self._log_edit.append(text)
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_refresh(self) -> None:
        """Called every frame to update triangle and title."""
        self._triangle.update()

        elapsed = time.perf_counter() - self._start_time
        remaining = max(0, self._duration - elapsed)
        fps = self._triangle.fps

        m = metrics.summary()
        self.setWindowTitle(
            f"FPS: {fps:.1f} | "
            f"Tasks: {m['tasks_created']}/{m['tasks_completed']} | "
            f"Steps: {m['task_steps']} | "
            f"Callbacks: {m['callbacks_executed']} | "
            f"Remaining: {remaining:.1f}s"
        )

        # Log FPS to stderr every second for real-time terminal visibility
        now = time.perf_counter()
        if now - self._last_fps_log_time >= 1.0:
            self._last_fps_log_time = now
            import sys
            sys.stderr.write(
                f"\r[FPS] {fps:.1f} | "
                f"tasks={m['tasks_created']}/{m['tasks_completed']} | "
                f"steps={m['task_steps']} | "
                f"cbs={m['callbacks_executed']} | "
                f"t={elapsed:.0f}s"
            )
            sys.stderr.flush()

        # Auto-close
        if elapsed >= self._duration and not self._closed:
            self._closed = True
            import sys
            sys.stderr.write("\n")  # newline after the \r FPS line
            sys.stderr.flush()
            self.log(f"[AUTO-CLOSE] Test duration ({self._duration}s) reached.")
            self.log(f"[METRICS] {m}")
            self._refresh_timer.stop()
            perf_logger.remove(self._sink_id)
            # Stop the event loop
            loop = asyncio.get_event_loop()
            loop.stop()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closed = True
        self._refresh_timer.stop()
        try:
            perf_logger.remove(self._sink_id)
        except ValueError:
            pass
        event.accept()


def run_test(
    test_coro: TestCoroutine,
    *,
    duration: float = 5.0,
    title: str = "Helix Perf Test",
) -> None:
    """
    Run a performance test with the standard UI harness.

    Args:
        test_coro: An async function receiving the PerfTestWindow.
                   It will be scheduled as a task on the helix event loop.
        duration: Seconds before auto-close.
        title: Window title prefix.
    """
    # Reset metrics for a clean test
    metrics.reset()

    app = QApplication.instance() or QApplication(sys.argv)

    window = PerfTestWindow(title=title, duration=duration)
    window.show()

    async def _main():
        window.log(f"[START] Test: {title} | Duration: {duration}s")
        try:
            await test_coro(window)
        except asyncio.CancelledError:
            window.log("[INFO] Test coroutine cancelled (expected on auto-close)")
        except Exception as e:
            window.log(f"[ERROR] {type(e).__name__}: {e}")

    helix.run(_main(), keep_running=True, quit_qapp=True)
