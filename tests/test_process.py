"""Process supervision streams output and terminates process groups."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.process import run_bounded_capture, run_process  # noqa: E402


class ProcessTests(unittest.TestCase):
    def test_bounded_capture_drains_but_retains_only_the_declared_limit(self) -> None:
        payload_size = 512 * 1024
        limit = 4096
        result = run_bounded_capture(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    f"os.write(1, b'x' * {payload_size}); "
                    f"os.write(2, b'y' * {payload_size})"
                ),
            ],
            env=os.environ,
            timeout_seconds=5,
            max_bytes=limit,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual(limit, len(result.stdout))
        self.assertEqual(limit, len(result.stderr))
        self.assertEqual(payload_size, result.stdout_bytes)
        self.assertEqual(payload_size, result.stderr_bytes)
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)

    def test_timeout_returns_124_and_retains_both_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            devnull = os.open(os.devnull, os.O_WRONLY)
            try:
                result = run_process(
                    [sys.executable, "-c", "import sys,time; print('out', flush=True); print('err', file=sys.stderr, flush=True); time.sleep(5)"],
                    env=os.environ,
                    stdin=None,
                    stdout_path=root / "stdout.log",
                    stderr_path=root / "stderr.log",
                    timeout_seconds=0.2,
                    cwd=root,
                    terminal_stdout_fd=devnull,
                    terminal_stderr_fd=devnull,
                )
            finally:
                os.close(devnull)
            self.assertEqual(124, result.exit_code)
            self.assertTrue(result.timed_out)
            self.assertEqual(b"out\n", (root / "stdout.log").read_bytes())
            self.assertEqual(b"err\n", (root / "stderr.log").read_bytes())


if __name__ == "__main__":
    unittest.main()
