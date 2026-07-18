"""Installer tests for the public entrypoint symlinks."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_installer_links_runtime_and_all_five_shims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "scripts"
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "scripts/install.sh"), str(destination)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr.decode(errors="replace"))
            for name in (
                "model-routing",
                "codex-shim.sh",
                "claude-shim.sh",
                "grok-shim.sh",
                "kimi-shim.sh",
                "opencode-shim.sh",
            ):
                with self.subTest(name=name):
                    link = destination / name
                    self.assertTrue(link.is_symlink())
                    self.assertEqual((ROOT / "scripts" / name).resolve(), link.resolve())

    def test_installer_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "scripts"
            for _ in range(2):
                result = subprocess.run(
                    ["/bin/bash", str(ROOT / "scripts/install.sh"), str(destination)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ,
                    check=False,
                )
                self.assertEqual(0, result.returncode)
            self.assertIn("already linked: model-routing", result.stdout.decode())


if __name__ == "__main__":
    unittest.main()
