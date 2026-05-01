"""
Headless HTTP test — prints results to terminal.
Tests GET, POST, PUT, PATCH, DELETE via niquests through helix event loop.
Uses httpbin.org (delayed + JSON endpoints) to verify non-blocking behavior.
"""

import asyncio
from PySide6.QtWidgets import QApplication
import time

import niquests

import helix

BASE = "https://httpbin.org"


async def main():
    print("HTTP Methods Test (niquests + helix)")
    print("=" * 60)
    print()

    async with niquests.AsyncSession() as s:
        # --- GET /delay/1 ---
        t0 = time.perf_counter()
        r = await s.get(f"{BASE}/delay/1")
        ms = (time.perf_counter() - t0) * 1000
        d = r.json()
        origin = d.get("origin", "?")
        print(f"  [GET]    /delay/1       {r.status_code}  {ms:6.0f}ms  origin={origin}")
        assert r.status_code == 200

        # --- GET /json ---
        t0 = time.perf_counter()
        r = await s.get(f"{BASE}/json")
        ms = (time.perf_counter() - t0) * 1000
        d = r.json()
        title = d["slideshow"]["title"]
        print(f"  [GET]    /json          {r.status_code}  {ms:6.0f}ms  title={title!r}")
        assert r.status_code == 200

        # --- POST /post ---
        payload = {"msg": "hello from helix", "numbers": [1, 2, 3]}
        t0 = time.perf_counter()
        r = await s.post(f"{BASE}/post", json=payload)
        ms = (time.perf_counter() - t0) * 1000
        d = r.json()
        echoed = d.get("json") or d.get("data")
        print(f"  [POST]   /post          {r.status_code}  {ms:6.0f}ms  echo={echoed}")
        assert r.status_code == 200

        # --- PUT /put ---
        payload = {"updated": True, "value": 42}
        t0 = time.perf_counter()
        r = await s.put(f"{BASE}/put", json=payload)
        ms = (time.perf_counter() - t0) * 1000
        d = r.json()
        echoed = d.get("json") or d.get("data")
        print(f"  [PUT]    /put           {r.status_code}  {ms:6.0f}ms  echo={echoed}")
        assert r.status_code == 200

        # --- PATCH /patch ---
        payload = {"patched_field": "new_value"}
        t0 = time.perf_counter()
        r = await s.patch(f"{BASE}/patch", json=payload)
        ms = (time.perf_counter() - t0) * 1000
        d = r.json()
        echoed = d.get("json") or d.get("data")
        print(f"  [PATCH]  /patch         {r.status_code}  {ms:6.0f}ms  echo={echoed}")
        assert r.status_code == 200

        # --- DELETE /delete ---
        payload = {"id": 99}
        t0 = time.perf_counter()
        r = await s.delete(f"{BASE}/delete", json=payload)
        ms = (time.perf_counter() - t0) * 1000
        d = r.json()
        echoed = d.get("json") or d.get("data")
        print(f"  [DELETE] /delete        {r.status_code}  {ms:6.0f}ms  echo={echoed}")
        assert r.status_code == 200

        print()

        # --- Concurrent: 5x GET /delay/2 ---
        print("  [CONCURRENT] 5x GET /delay/2 in parallel ...")
        t0 = time.perf_counter()
        tasks = [asyncio.create_task(s.get(f"{BASE}/delay/2")) for _ in range(5)]
        results = await asyncio.gather(*tasks)
        ms = (time.perf_counter() - t0) * 1000
        codes = [r.status_code for r in results]
        print(f"    statuses = {codes}")
        print(f"    total    = {ms:.0f}ms (sequential would be ~10,000ms)")
        assert all(c == 200 for c in codes)
        assert ms < 8000, f"Took {ms:.0f}ms — possible blocking!"

    print()
    print("=" * 60)
    print("  ALL PASSED — non-blocking HTTP confirmed")
    print("=" * 60)


if __name__ == "__main__":
    app = QApplication([])
    helix.run(main(), app=app, keep_running=False)
