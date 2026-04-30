"""
Test: Download Performance (niquests + mock 1GB server)

Spins up a local threaded HTTP server that streams a 1 GB response of
deterministic bytes, then launches 50 concurrent async coroutines each
downloading the full file through niquests.AsyncSession over the helix
event loop.

Tracks per-coroutine progress, aggregate throughput, and event-loop health
(FPS, task steps, callbacks) in real time.
"""

from __future__ import annotations

import asyncio
import os
import socket
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(__file__))
os.environ["HELIX_PERF_LOG"] = "1"
os.environ["HELIX_PERF_LOG_LEVEL"] = "DEBUG"

import niquests

from test_ui import PerfTestWindow, run_test

from helix.logging import log_event, metrics

# ---------------------------------------------------------------------------
# Mock HTTP server that streams a 1 GB response
# ---------------------------------------------------------------------------

FILE_SIZE = 1 * 1024 * 1024 * 1024  # 1 GB
CHUNK_SIZE = 256 * 1024  # 256 KB per write
# Pre-generate one chunk of deterministic bytes to avoid per-request cost
_CHUNK_DATA = bytes(range(256)) * (CHUNK_SIZE // 256)

CONCURRENCY = 50
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 0  # auto-pick a free port


class MockFileHandler(BaseHTTPRequestHandler):
    """Streams CHUNK_SIZE chunks until FILE_SIZE bytes are sent."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(FILE_SIZE))
        self.send_header("Connection", "close")
        self.end_headers()

        sent = 0
        while sent < FILE_SIZE:
            to_send = min(CHUNK_SIZE, FILE_SIZE - sent)
            try:
                self.wfile.write(_CHUNK_DATA[:to_send])
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                break
            sent += to_send

    # Silence per-request log lines on stderr
    def log_message(self, format, *args):  # noqa: A002
        pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Handle each request in a new thread so 50 concurrent downloads work."""

    address_family = socket.AF_INET  # Force IPv4 only
    daemon_threads = True
    allow_reuse_address = True

    # Increase the listen backlog for 50 concurrent connections
    request_queue_size = 128


def _start_server() -> tuple[ThreadedHTTPServer, int]:
    """Start the mock server in a daemon thread, return (server, port)."""
    server = ThreadedHTTPServer((SERVER_HOST, SERVER_PORT), MockFileHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


# ---------------------------------------------------------------------------
# Download coroutine
# ---------------------------------------------------------------------------

# Shared mutable state for progress tracking
_progress: dict[int, dict] = {}


async def _download_one(
    coro_id: int,
    url: str,
    session: niquests.AsyncSession,
    window: PerfTestWindow,
) -> dict:
    """Download the mock file, tracking bytes received and elapsed time."""
    _progress[coro_id] = {"bytes": 0, "done": False, "elapsed_ms": 0}

    start = time.perf_counter()
    total_bytes = 0

    try:
        resp = await session.get(url, stream=True)
        async for chunk in await resp.iter_content(chunk_size=CHUNK_SIZE):
            total_bytes += len(chunk)
            _progress[coro_id]["bytes"] = total_bytes
    except (asyncio.CancelledError, Exception) as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        _progress[coro_id]["elapsed_ms"] = elapsed_ms
        _progress[coro_id]["done"] = True
        if isinstance(exc, asyncio.CancelledError):
            raise
        # Log but don't crash the test
        window.log(
            f"[DL-{coro_id:02d}] ERROR after {total_bytes / 1e6:.1f} MB: {exc}"
        )
        return {
            "id": coro_id,
            "bytes": total_bytes,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }

    elapsed_ms = (time.perf_counter() - start) * 1000
    _progress[coro_id]["elapsed_ms"] = elapsed_ms
    _progress[coro_id]["done"] = True

    window.log(
        f"[DL-{coro_id:02d}] DONE  {total_bytes / (1024**3):.2f} GB "
        f"in {elapsed_ms:,.0f} ms"
    )

    return {
        "id": coro_id,
        "bytes": total_bytes,
        "elapsed_ms": elapsed_ms,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Progress reporter coroutine
# ---------------------------------------------------------------------------


async def _report_progress(window: PerfTestWindow) -> None:
    """Periodically log aggregate download progress."""
    import gc
    import sys

    t0 = time.perf_counter()
    prev_bytes = 0
    prev_steps = 0
    fps_samples: list[float] = []

    while True:
        await asyncio.sleep(2.0)

        total_bytes = sum(p["bytes"] for p in _progress.values())
        done_count = sum(1 for p in _progress.values() if p["done"])
        active = len(_progress) - done_count

        total_mb = total_bytes / (1024 * 1024)
        total_gb = total_bytes / (1024 * 1024 * 1024)
        target_gb = CONCURRENCY

        # Instantaneous throughput over this reporting interval
        delta_bytes = total_bytes - prev_bytes
        prev_bytes = total_bytes
        instant_mbps = (delta_bytes * 8) / 2.0 / 1e6  # 2s interval

        elapsed = time.perf_counter() - t0

        # FPS from the triangle widget
        fps = window.triangle.fps
        fps_samples.append(fps)

        m = metrics.summary()
        steps_delta = m['task_steps'] - prev_steps
        prev_steps = m['task_steps']

        # Ready queue depth
        loop = asyncio.get_event_loop()
        queue_depth = len(loop._ready_queue) if hasattr(loop, '_ready_queue') else -1

        # GC and memory
        gc_counts = gc.get_count()
        # RSS approximation via gc tracked objects
        gc_tracked = len(gc.get_objects())

        window.log(
            f"[PROGRESS] FPS={fps:.1f} | "
            f"{total_mb:,.0f} MB ({total_gb:.2f}/{target_gb} GB) | "
            f"{instant_mbps:,.0f} Mbps | "
            f"active={active} done={done_count}/{CONCURRENCY} | "
            f"steps/2s={steps_delta} qd={queue_depth} | "
            f"gc={gc_counts} tracked={gc_tracked} | "
            f"elapsed={elapsed:.0f}s"
        )
        # Also print to stderr for terminal visibility
        import sys as _sys
        _sys.stderr.write(
            f"\n[DIAG] FPS={fps:.1f} steps/2s={steps_delta} qd={queue_depth} "
            f"gc={gc_counts} tracked={gc_tracked} mb={total_mb:,.0f}\n"
        )
        _sys.stderr.flush()

        if done_count >= len(_progress) and len(_progress) == CONCURRENCY:
            break

    # Log FPS summary
    if fps_samples:
        avg_fps = sum(fps_samples) / len(fps_samples)
        min_fps = min(fps_samples)
        max_fps = max(fps_samples)
        window.log(
            f"[FPS SUMMARY] avg={avg_fps:.1f} min={min_fps:.1f} "
            f"max={max_fps:.1f} samples={len(fps_samples)}"
        )


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------


async def test_download(window: PerfTestWindow) -> None:
    server, port = _start_server()
    url = f"http://{SERVER_HOST}:{port}/mock_1gb"

    window.log(f"[SERVER] Threaded mock HTTP server on :{port}  (1 GB per request)")
    window.log(f"[TEST]   Launching {CONCURRENCY} concurrent downloads...")
    window.log(
        f"[TEST]   Total target: {CONCURRENCY} GB over loopback "
        f"({CHUNK_SIZE // 1024} KB chunks)"
    )

    log_event(
        "download_test.start",
        concurrency=CONCURRENCY,
        file_size_gb=FILE_SIZE / (1024**3),
        chunk_size_kb=CHUNK_SIZE // 1024,
    )

    # Start progress reporter
    reporter = asyncio.ensure_future(_report_progress(window))

    t0 = time.perf_counter()

    # Disable IPv6 so niquests doesn't try ::1 for 127.0.0.1
    async with niquests.AsyncSession(disable_ipv6=True) as session:
        tasks = [
            asyncio.ensure_future(_download_one(i, url, session, window))
            for i in range(CONCURRENCY)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    wall_ms = (time.perf_counter() - t0) * 1000

    reporter.cancel()
    try:
        await reporter
    except asyncio.CancelledError:
        pass

    # --- Summary ---
    completed = [
        r for r in results if isinstance(r, dict) and r.get("error") is None
    ]
    errored = [
        r for r in results if isinstance(r, dict) and r.get("error") is not None
    ]
    cancelled = [r for r in results if isinstance(r, BaseException)]

    total_bytes = sum(r["bytes"] for r in results if isinstance(r, dict))
    total_gb = total_bytes / (1024**3)

    avg_ms = (
        sum(r["elapsed_ms"] for r in completed) / len(completed)
        if completed
        else 0
    )
    throughput_mbps = (total_bytes * 8) / (wall_ms / 1000) / 1e6 if wall_ms > 0 else 0

    m = metrics.summary()

    window.log("")
    window.log("=" * 60)
    window.log("[SUMMARY] Download test complete")
    window.log(f"  Concurrency     : {CONCURRENCY}")
    window.log(f"  Completed       : {len(completed)}")
    window.log(f"  Errored         : {len(errored)}")
    window.log(f"  Cancelled       : {len(cancelled)}")
    window.log(f"  Total data      : {total_gb:.2f} GB")
    window.log(f"  Wall time       : {wall_ms:,.0f} ms")
    window.log(f"  Avg per-coro    : {avg_ms:,.0f} ms")
    window.log(f"  Throughput      : {throughput_mbps:,.0f} Mbps")
    window.log(f"  Tasks created   : {m['tasks_created']}")
    window.log(f"  Tasks completed : {m['tasks_completed']}")
    window.log(f"  Task steps      : {m['task_steps']}")
    window.log(f"  Callbacks sched : {m['callbacks_scheduled']}")
    window.log(f"  Callbacks exec  : {m['callbacks_executed']}")
    window.log(f"  Step time total : {m['total_task_step_time_us']}μs")
    window.log(f"  CB time total   : {m['total_callback_time_us']}μs")
    window.log("=" * 60)

    log_event(
        "download_test.end",
        completed=len(completed),
        errored=len(errored),
        total_gb=f"{total_gb:.2f}",
        wall_ms=f"{wall_ms:.0f}",
        throughput_mbps=f"{throughput_mbps:.0f}",
    )

    server.shutdown()


if __name__ == "__main__":
    # 30s duration — enough to observe FPS degradation under heavy I/O load
    run_test(test_download, duration=30.0, title="Download Performance (50x1GB)")
