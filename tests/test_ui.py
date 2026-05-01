import asyncio
import math
import sys
import time
from typing import Awaitable, Callable

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QElapsedTimer,
    QPointF,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
    QTimer,
)
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
    """A widget that renders a continuously rotating and scaling"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fps = 0.0
        self.frame_count = 0
        self.last_fps_time = time.perf_counter()
        self.elapsed = QElapsedTimer()
        self.elapsed.start()
        self.angle_value = 0.0
        self.scale_value = 20.0
        self.setup_animations()

    def get_angle(self) -> float:
        return self.angle_value

    def set_angle(self, value: float) -> None:
        self.angle_value = value
        self.update()

    def get_scale(self) -> float:
        return self.scale_value

    def set_scale(self, value: float) -> None:
        self.scale_value = value
        self.update()


    def setup_animations(self) -> None:
        # Rotation: continuous 0 -> 360 over 4 seconds, looping forever
        self.rotation_anim = QPropertyAnimation(self, b"angle")
        self.rotation_anim.setDuration(4000)
        self.rotation_anim.setStartValue(0.0)
        self.rotation_anim.setEndValue(360.0)
        self.rotation_anim.setLoopCount(-1)
        self.rotation_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self.rotation_anim.start()

        # Scale: ping-pong between 20 and 150 using a sequential group
        self.scale_group = QSequentialAnimationGroup(self)

        grow = QPropertyAnimation(self, b"scale")
        grow.setDuration(5000)
        grow.setStartValue(20.0)
        grow.setEndValue(150.0)
        grow.setEasingCurve(QEasingCurve.Type.InOutSine)

        shrink = QPropertyAnimation(self, b"scale")
        shrink.setDuration(5000)
        shrink.setStartValue(150.0)
        shrink.setEndValue(20.0)
        shrink.setEasingCurve(QEasingCurve.Type.InOutSine)

        self.scale_group.addAnimation(grow)
        self.scale_group.addAnimation(shrink)
        self.scale_group.setLoopCount(-1)
        self.scale_group.start()

        # Direction: toggle rotation direction every 6 seconds
        self.direction_timer = QTimer(self)
        self.direction_timer.setInterval(6000)
        self.direction_timer.timeout.connect(self.toggle_direction)
        self.direction_timer.start()

    def toggle_direction(self) -> None:
        """Toggle rotation direction using Qt's native Direction enum."""
        if self.rotation_anim.direction() == QAbstractAnimation.Direction.Forward:
            self.rotation_anim.setDirection(QAbstractAnimation.Direction.Backward)
        else:
            self.rotation_anim.setDirection(QAbstractAnimation.Direction.Forward)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.frame_count += 1
        now = time.perf_counter()
        dt = now - self.last_fps_time
        if dt >= 1.0:
            self.fps = self.frame_count / dt if dt > 0 else 0
            self.frame_count = 0
            self.last_fps_time = now

        elapsed_sec = self.elapsed.elapsed() / 1000.0
        angle_rad = math.radians(self.angle_value)
        size = self.scale_value

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

    scale = Property(float, get_scale, set_scale)
    angle = Property(float, get_angle, set_angle)


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
        self.duration = duration
        self.start_time = time.perf_counter()
        self.closed = False

        self.setWindowTitle(title)
        self.resize(600, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Vertical)

        self.triangle = TriangleWidget()
        splitter.addWidget(self.triangle)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, monospace; font-size: 10pt; }"
        )
        splitter.addWidget(self.log_edit)

        splitter.setSizes([200, 300])
        layout.addWidget(splitter)

        # Refresh timer drives animation and title updates (~60 FPS)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(16)
        self.refresh_timer.timeout.connect(self.on_refresh)
        self.refresh_timer.start()

    def log(self, message: str) -> None:
        """Append a message to the log panel."""
        self.log_edit.append(message)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_refresh(self) -> None:
        self.triangle.update()

        elapsed = time.perf_counter() - self.start_time
        remaining = max(0, self.duration - elapsed)
        fps = self.triangle.fps

        self.setWindowTitle(f"FPS: {fps:.1f} | Remaining: {remaining:.1f}s")

        # Auto-close
        if elapsed >= self.duration and not self.closed:
            self.closed = True
            self.log(f"[AUTO-CLOSE] Duration ({self.duration}s) reached. FPS={fps:.1f}")
            self.refresh_timer.stop()
            loop = asyncio.get_event_loop()
            loop.stop()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed = True
        self.refresh_timer.stop()
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

    async def main():
        window.log(f"[START] {title} | Duration: {duration}s")
        try:
            await test_coro(window)
        except asyncio.CancelledError:
            window.log("[INFO] Test cancelled (expected on auto-close)")
        except Exception as e:
            window.log(f"[ERROR] {type(e).__name__}: {e}")

    helix.run(main(), keep_running=True, app=app, quit_qapp=True)
