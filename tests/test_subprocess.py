"""Test subprocess support under QtEventLoop."""

import asyncio
import sys
import traceback

from PySide6.QtWidgets import QApplication

import helix


async def test_subprocess_exec():
    """Test basic subprocess_exec with stdout/stderr capture."""
    print("\n--- test_subprocess_exec ---")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "print('hello from subprocess')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, f"Expected returncode 0, got {process.returncode}"
    assert b"hello from subprocess" in stdout, f"Unexpected stdout: {stdout}"
    print("PASS")


async def test_subprocess_shell():
    """Test subprocess_shell."""
    print("\n--- test_subprocess_shell ---")
    process = await asyncio.create_subprocess_shell(
        f'{sys.executable} -c "import sys; sys.stdout.write(\'shell ok\')"',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, f"Expected returncode 0, got {process.returncode}"
    assert b"shell ok" in stdout, f"Unexpected stdout: {stdout}"
    print("PASS")


async def test_subprocess_stdin():
    """Test writing to subprocess stdin."""
    print("\n--- test_subprocess_stdin ---")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; data = sys.stdin.read(); sys.stdout.write(f'got: {data}')",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(input=b"ping")
    assert process.returncode == 0, f"Expected returncode 0, got {process.returncode}"
    assert b"got: ping" in stdout, f"Unexpected stdout: {stdout}"
    print("PASS")


async def test_subprocess_returncode():
    """Test non-zero return code."""
    print("\n--- test_subprocess_returncode ---")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.exit(42)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await process.wait()
    assert process.returncode == 42, f"Expected returncode 42, got {process.returncode}"
    print("PASS")


async def test_subprocess_stderr():
    """Test stderr capture."""
    print("\n--- test_subprocess_stderr ---")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('error output')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, f"Expected returncode 0, got {process.returncode}"
    assert b"error output" in stderr, f"Unexpected stderr: {stderr}"
    print("PASS")


async def main():
    print(f"loop={type(asyncio.get_running_loop()).__name__}")
    tests = [
        test_subprocess_exec,
        test_subprocess_shell,
        test_subprocess_stdin,
        test_subprocess_returncode,
        test_subprocess_stderr,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception:
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print("SOME TESTS FAILED")
    else:
        print("ALL TESTS PASSED")

    asyncio.get_running_loop().stop()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    loop = helix.QtEventLoop(app)
    asyncio.set_event_loop(loop)
    loop.create_task(main())
    loop.run_forever()
    loop.close()
