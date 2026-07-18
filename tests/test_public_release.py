"""Tests for the explicit public release boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import build_public_release


ROOT = Path(__file__).resolve().parents[1]


class PublicReleaseTests(unittest.TestCase):
    def test_build_contains_product_and_excludes_private_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "candidate"
            files = build_public_release.build_release(ROOT, destination)
            self.assertTrue((destination / "runtime/model_routing/provider_setup.py").is_file())
            self.assertTrue((destination / "scripts/kimi-shim.sh").is_file())
            self.assertTrue((destination / "references/README.md").is_file())
            self.assertFalse((destination / "PROJECT-CONTEXT.md").exists())
            self.assertFalse((destination / "DESIGN.md").exists())
            self.assertFalse((destination / "docs/superpowers").exists())
            self.assertFalse((destination / "references/system-cards").exists())
            self.assertNotIn(Path("PROJECT-CONTEXT.md"), files)

            manifest = json.loads(
                (destination / build_public_release.RELEASE_MANIFEST).read_text(encoding="utf-8")
            )
            self.assertEqual(len(files), manifest["fileCount"])
            for record in manifest["files"]:
                content = (destination / record["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), record["sha256"])

    def test_destination_must_be_new_and_external(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "candidate"
            destination.mkdir()
            with self.assertRaisesRegex(build_public_release.PublicReleaseError, "already exists"):
                build_public_release.build_release(ROOT, destination)
        with self.assertRaisesRegex(build_public_release.PublicReleaseError, "outside"):
            build_public_release.build_release(ROOT, ROOT / "candidate")

    def test_private_text_rules_cover_release_blockers(self) -> None:
        cases = {
            "/home/" + "alice/git/project": "maintainer home path",
            "ssh://git@" + "git.internal.example/repo": "private infrastructure domain",
            "alice@" + "protonmail.com": "personal Proton Mail address",
            "-----BEGIN " + "OPENSSH PRIVATE KEY-----": "private key material",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIn(
                    expected,
                    build_public_release.private_text_findings(Path("sample.txt"), text),
                )


if __name__ == "__main__":
    unittest.main()
