"""
Run all performance tests sequentially.

Each test opens a window with the animated triangle and log panel,
runs for its configured duration, then auto-closes.

Usage:
    python tests/run_all.py
"""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
TEST_FILES = [
    "test_event_loop.py",
    "test_task.py",
    "test_future.py",
    "test_callback.py",
    "test_executor.py",
]


def main():
    print("=" * 60)
    print("Helix Performance Test Suite")
    print("=" * 60)

    for test_file in TEST_FILES:
        path = TESTS_DIR / test_file
        print(f"\n{'─' * 60}")
        print(f"Running: {test_file}")
        print(f"{'─' * 60}")

        result = subprocess.run(
            [sys.executable, str(path)],
            env={
                **__import__("os").environ,
                "HELIX_PERF_LOG": "1",
                "HELIX_PERF_LOG_LEVEL": "DEBUG",
            },
        )

        if result.returncode != 0:
            print(f"  [FAIL] {test_file} exited with code {result.returncode}")
        else:
            print(f"  [PASS] {test_file}")

    print(f"\n{'=' * 60}")
    print("All tests completed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
