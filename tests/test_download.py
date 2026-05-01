"""
Test: Download Performance (niquests + mock 1GB server)

Spins up a local threaded HTTP server that streams 1 GB responses,
then launches 50 concurrent async downloads through the helix event loop.
Tracks FPS to verify UI responsiveness under heavy I/O load.
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

import niquests

from test_ui import PerfTestWindow, run_test

# ---------------------------------------------------------------------------
# Mock HTTP server
# ---------------------------------------------------------------------------

FILE_SIZE = 1 * 1024 * 1024 * 1024  # 1 GB
CHUNK_SIZE = 256 * 1024  # 256 KB per write
_CHUNK_DATA = bytes(range(256)) * (CHUNK_SIZE // 256)

CONCURRENCY = 50
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 0


class MockFileHandler(BaseHTTPRequestHandler):
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

    def log_message(self, format, *args):  # noqa: A002
        pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    address_family = socket.AF_INET
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


def _start_server() -> tuple[ThreadedHTTPServer, int]:
    server = ThreadedHTTPServer((SERVER_HOST, SERVER_PORT), MockFileHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


# ---------------------------------------------------------------------------
# Download coroutine
# ---------------------------------------------------------------------------


async def _download_one(
    coro_id: int,
    url: str,
    session: niquests.AsyncSession,
    window: PerfTestWindow,
    progress: dict,
) -> dict:
    progress[coro_id] = {"bytes": 0, "done": False}

    start = time.perf_counter()
    total_bytes = 0

    try:
        resp = await session.get(url, stream=True)
        async for chunk in await resp.iter_content(chunk_size=CHUNK_SIZE):
            total_bytes += len(chunk)
            progress[coro_id]["bytes"] = total_bytes
    except (asyncio.CancelledError, Exception) as exc:
        progress[coro_id]["done"] = True
        if isinstance(exc, asyncio.CancelledError):
            raise
        window.log(f"[DL-{coro_id:02d}] ERROR: {exc}")
        return {"id": coro_id, "bytes": total_bytes, "error": str(exc)}

    elapsed_ms = (time.perf_counter() - start) * 1000
    progress[coro_id]["done"] = True
    window.log(
        f"[DL-{coro_id:02d}] DONE {total_bytes / (1024**3):.2f} GB "
        f"in {elapsed_ms:,.0f} ms"
    )
    return {"id": coro_id, "bytes": total_bytes, "error": None}


# ---------------------------------------------------------------------------
# Progress reporter
# ---------------------------------------------------------------------------


async def _report_progress(window: PerfTestWindow, progress: dict) -> None:
    t0 = time.perf_counter()
    prev_bytes = 0

    while True:
        await asyncio.sleep(2.0)

        total_bytes = sum(p["bytes"] for p in progress.values())
        done_count = sum(1 for p in progress.values() if p["done"])
        active = len(progress) - done_count

        delta_bytes = total_bytes - prev_bytes
        prev_bytes = total_bytes
        mbps = (delta_bytes * 8) / 2.0 / 1e6

        elapsed = time.perf_counter() - t0
        fps = window.triangle.fps

        window.log(
            f"[PROGRESS] FPS={fps:.1f} | "
            f"{total_bytes / 1e6:,.0f} MB | "
            f"{mbps:,.0f} Mbps | "
            f"active={active} done={done_count}/{CONCURRENCY} | "
            f"t={elapsed:.0f}s"
        )

        if done_count >= CONCURRENCY and len(progress) == CONCURRENCY:
            break


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------


async def test_download(window: PerfTestWindow) -> None:
    server, port = _start_server()
    url = f"http://{SERVER_HOST}:{port}/mock_1gb"

    window.log(f"[SERVER] Mock HTTP on :{port} (1 GB/request)")
    window.log(f"[TEST] Launching {CONCURRENCY} concurrent downloads...")

    progress: dict = {}
    reporter = asyncio.create_task(_report_progress(window, progress))

    t0 = time.perf_counter()

    async with niquests.AsyncSession(disable_ipv6=True) as session:
        tasks = [
            asyncio.create_task(_download_one(i, url, session, window, progress))
            for i in range(CONCURRENCY)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    wall_ms = (time.perf_counter() - t0) * 1000

    reporter.cancel()
    try:
        await reporter
    except asyncio.CancelledError:
        pass

    # Summary
    completed = [r for r in results if isinstance(r, dict) and r.get("error") is None]
    total_bytes = sum(r["bytes"] for r in results if isinstance(r, dict))
    throughput_mbps = (total_bytes * 8) / (wall_ms / 1000) / 1e6 if wall_ms > 0 else 0

    window.log("")
    window.log("=" * 50)
    window.log(f"[SUMMARY] {len(completed)}/{CONCURRENCY} completed")
    window.log(f"  Data: {total_bytes / (1024**3):.2f} GB in {wall_ms:,.0f} ms")
    window.log(f"  Throughput: {throughput_mbps:,.0f} Mbps")
    window.log(f"  Final FPS: {window.triangle.fps:.1f}")
    window.log("=" * 50)

    server.shutdown()


if __name__ == "__main__":
    run_test(test_download, duration=30.0, title="Download Performance (50x1GB)")
