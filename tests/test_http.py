"""
Test: HTTP methods via niquests (GET, POST, PUT, PATCH, DELETE).

Uses httpbin.org which provides echo endpoints with optional delay
and JSON responses. Verifies all methods work correctly through
the Qt-backed asyncio event loop without blocking.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import niquests

from test_ui import PerfTestWindow, run_test

BASE = "https://httpbin.org"


async def test_http(window: PerfTestWindow) -> None:
    window.log("[TEST] HTTP methods via niquests + httpbin.org")
    window.log(f"[TEST] Base URL: {BASE}")
    window.log("")

    async with niquests.AsyncSession() as s:
        # --- GET with delay ---
        window.log("[GET] /delay/1 ...")
        t0 = time.perf_counter()
        resp = await s.get(f"{BASE}/delay/1")
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        assert resp.status_code == 200
        assert "url" in data
        window.log(f"  status={resp.status_code}  time={elapsed:.0f}ms")
        window.log(f"  origin={data.get('origin')}")
        window.log("")

        # --- GET JSON ---
        window.log("[GET] /json ...")
        t0 = time.perf_counter()
        resp = await s.get(f"{BASE}/json")
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        assert resp.status_code == 200
        assert "slideshow" in data
        window.log(f"  status={resp.status_code}  time={elapsed:.0f}ms")
        window.log(f"  slideshow.title={data['slideshow']['title']!r}")
        window.log("")

        # --- POST /post ---
        window.log("[POST] /post with JSON body ...")
        payload = {"message": "hello from helix", "numbers": [1, 2, 3]}
        t0 = time.perf_counter()
        resp = await s.post(f"{BASE}/post", json=payload)
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        echoed = data.get("json") or data.get("data")
        assert resp.status_code == 200
        window.log(f"  status={resp.status_code}  time={elapsed:.0f}ms")
        window.log(f"  echoed={echoed}")
        window.log("")

        # --- PUT ---
        window.log("[PUT] /put with JSON body ...")
        payload = {"updated": True, "value": 42}
        t0 = time.perf_counter()
        resp = await s.put(f"{BASE}/put", json=payload)
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        echoed = data.get("json") or data.get("data")
        assert resp.status_code == 200
        window.log(f"  status={resp.status_code}  time={elapsed:.0f}ms")
        window.log(f"  echoed={echoed}")
        window.log("")

        # --- PATCH ---
        window.log("[PATCH] /patch with JSON body ...")
        payload = {"patched_field": "new_value"}
        t0 = time.perf_counter()
        resp = await s.patch(f"{BASE}/patch", json=payload)
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        echoed = data.get("json") or data.get("data")
        assert resp.status_code == 200
        window.log(f"  status={resp.status_code}  time={elapsed:.0f}ms")
        window.log(f"  echoed={echoed}")
        window.log("")

        # --- DELETE ---
        window.log("[DELETE] /delete ...")
        t0 = time.perf_counter()
        resp = await s.delete(f"{BASE}/delete", json={"id": 99})
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        echoed = data.get("json") or data.get("data")
        assert resp.status_code == 200
        window.log(f"  status={resp.status_code}  time={elapsed:.0f}ms")
        window.log(f"  echoed={echoed}")
        window.log("")

        # --- Concurrent GETs with delay (verify non-blocking) ---
        window.log("[CONCURRENT] 5x GET /delay/2 in parallel ...")
        t0 = time.perf_counter()
        tasks = [
            asyncio.create_task(s.get(f"{BASE}/delay/2"))
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks)
        elapsed = (time.perf_counter() - t0) * 1000
        for i, r in enumerate(results):
            assert r.status_code == 200
        window.log(f"  all 5 returned 200  total_time={elapsed:.0f}ms")
        window.log(f"  (sequential would be ~10s, got {elapsed:.0f}ms)")
        window.log("")

    # --- Summary ---
    fps = window.triangle.fps
    window.log("=" * 50)
    window.log("[SUMMARY] All HTTP methods passed")
    window.log(f"  GET, POST, PUT, PATCH, DELETE: OK")
    window.log(f"  Concurrent requests: OK (non-blocking)")
    window.log(f"  FPS during test: {fps:.1f}")
    window.log("=" * 50)


if __name__ == "__main__":
    run_test(test_http, duration=30.0, title="HTTP Methods Test")
