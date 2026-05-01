"""
Shared UI module for Helix performance tests.

Provides a reusable test harness with:
- An expanding/rotating triangle rendered via QPainter
- A QTextEdit log panel
- Real-time FPS display in the window title
- Auto-close after a configurable duration

Usage:
    from test_ui import PerfTestWindow, run_test

    async def my_test(window: PerfTestWindow):
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

from PySide6.QtCore import QElapsedTimer, QPointF, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import helix

# Type alias for the async test coroutine factory
TestCoroutine = Callable[["PerfTestWindow"], Awaitable[None]]


class TriangleWidget(QWidget):
    """
    A widget that renders a continuously expanding and rotating triangle.
    Serves as a visual indicator that the event loop is running smoothly.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._frame_count = 0
        self._fps = 0.0
        self._last_fps_time = time.perf_counter()
        self._base_size = 20.0
        self._max_size = 150.0
        self._growth_rate = 15.0
        self._rotation_speed = 90.0
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

        # Expanding size (10-second cycle)
        cycle = elapsed_sec % 10.0
        size = self._base_size + self._growth_rate * cycle
        size = min(size, self._max_size)

        # Rotation
        angle_rad = math.radians(elapsed_sec * self._rotation_speed)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        points = QPolygonF()
        for i in range(3):
            a = angle_rad + i * (2.0 * math.pi / 3.0)
            px = cx + size * math.cos(a)
            py = cy + size * math.sin(a)
            points.append(QPointF(px, py))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hue = int(elapsed_sec * 36) % 360
        color = QColor.fromHsv(hue, 200, 240)
        painter.setPen(QPen(color, 2))
        painter.setBrush(QBrush(color.lighter(150)))
        painter.drawPolygon(points)
        painter.end()


class PerfTestWindow(QWidget):
    """
    Main test window: animated triangle + log panel.
    """

    def __init__(
        self,
        title: str = "Helix Test",
        duration: float = 5.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._duration = duration
        self._start_time = time.perf_counter()
        self._closed = False

        self.setWindowTitle(title)
        self.resize(600, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter()
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

        # Refresh timer drives animation and title updates (~60 FPS)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(16)
        self._refresh_timer.timeout.connect(self._on_refresh)
        self._refresh_timer.start()

    @property
    def triangle(self) -> TriangleWidget:
        return self._triangle

    def log(self, message: str) -> None:
        """Append a message to the log panel."""
        self._log_edit.append(message)
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_refresh(self) -> None:
        self._triangle.update()

        elapsed = time.perf_counter() - self._start_time
        remaining = max(0, self._duration - elapsed)
        fps = self._triangle.fps

        self.setWindowTitle(
            f"FPS: {fps:.1f} | Remaining: {remaining:.1f}s"
        )

        # Auto-close
        if elapsed >= self._duration and not self._closed:
            self._closed = True
            self.log(f"[AUTO-CLOSE] Duration ({self._duration}s) reached. FPS={fps:.1f}")
            self._refresh_timer.stop()
            loop = asyncio.get_event_loop()
            loop.stop()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closed = True
        self._refresh_timer.stop()
        event.accept()


def run_test(
    test_coro: TestCoroutine,
    *,
    duration: float = 5.0,
    title: str = "Helix Test",
) -> None:
    """
    Run a performance test with the standard UI harness.

    Args:
        test_coro: An async function receiving the PerfTestWindow.
        duration:  Seconds before auto-close.
        title:     Window title.
    """
    app = QApplication.instance() or QApplication(sys.argv)

    window = PerfTestWindow(title=title, duration=duration)
    window.show()

    async def _main():
        window.log(f"[START] {title} | Duration: {duration}s")
        try:
            await test_coro(window)
        except asyncio.CancelledError:
            window.log("[INFO] Test cancelled (expected on auto-close)")
        except Exception as e:
            window.log(f"[ERROR] {type(e).__name__}: {e}")

    helix.run(_main(), keep_running=True, app=app, quit_qapp=True)
