"""Tests for canonical registry validation and host-specific generation."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.registry import RegistryError, load_registry, validate_registry  # noqa: E402
from tools.sync_routes import generated_files  # noqa: E402


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry(ROOT / "config" / "provider-registry.json")

    def test_schema_documents_are_valid_json(self) -> None:
        for path in (ROOT / "schemas").glob("*.schema.json"):
            with self.subTest(path=path.name):
                self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_registry_has_expected_host_boundaries(self) -> None:
        files = generated_files(self.registry)
        payloads = {}
        for host_id, host in self.registry["hosts"].items():
            path = ROOT / host["packagePath"] / "skills/subagent-model-routing/references/provider-registry.generated.json"
            payloads[host_id] = json.loads(files[path])
        self.assertNotIn("claude", payloads["claude"]["providers"])
        self.assertNotIn("codex", payloads["codex"]["providers"])
        self.assertEqual(
            {"codex", "claude", "grok", "kimi", "opencode"},
            set(payloads["copilot"]["providers"]),
        )

    def test_generated_files_match_committed_content(self) -> None:
        for path, expected in generated_files(self.registry).items():
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), path)
                self.assertEqual(expected, path.read_text(encoding="utf-8"))

    def test_registry_has_no_mythos_surface(self) -> None:
        self.assertNotIn("mythos", json.dumps(self.registry).lower())

    def test_duplicate_model_alias_is_rejected(self) -> None:
        data = json.loads(json.dumps(self.registry))
        data["providers"]["grok"]["models"]["grok-4.5"]["aliases"] = ["sonnet"]
        with self.assertRaisesRegex(RegistryError, "duplicated"):
            validate_registry(data, repo_root=ROOT)

    def test_registry_adapter_contracts_are_aligned(self) -> None:
        validate_registry(json.loads(json.dumps(self.registry)), repo_root=ROOT)

    def test_kimi_declares_config_probe_and_no_effort_control(self) -> None:
        kimi = self.registry["providers"]["kimi"]
        self.assertTrue(kimi["capabilities"]["configProbe"])
        self.assertEqual({"kind": "none", "key": None, "values": []}, kimi["effort"])

    def test_required_provider_objects_are_rejected_when_missing(self) -> None:
        for field in ("effort", "capabilities"):
            with self.subTest(field=field):
                data = json.loads(json.dumps(self.registry))
                del data["providers"]["codex"][field]
                with self.assertRaisesRegex(RegistryError, field):
                    validate_registry(data, repo_root=ROOT)

    def test_required_model_and_family_fields_are_rejected_when_missing(self) -> None:
        cases = (
            ("models", "displayName"),
            ("models", "provenance"),
            ("routeFamilies", "displayName"),
        )
        for collection, field in cases:
            with self.subTest(collection=collection, field=field):
                data = json.loads(json.dumps(self.registry))
                if collection == "models":
                    del data["providers"]["codex"][collection]["gpt-5.6-sol"][field]
                else:
                    del data["providers"]["opencode"][collection][0][field]
                with self.assertRaisesRegex(RegistryError, field):
                    validate_registry(data, repo_root=ROOT)

    def test_invalid_ids_and_empty_required_lists_are_rejected(self) -> None:
        for family_id in ("Kimi", "../etc"):
            with self.subTest(family_id=family_id):
                data = json.loads(json.dumps(self.registry))
                data["providers"]["opencode"]["routeFamilies"][0]["id"] = family_id
                with self.assertRaisesRegex(RegistryError, "invalid format|parent path"):
                    validate_registry(data, repo_root=ROOT)
        data = json.loads(json.dumps(self.registry))
        data["providers"]["codex"]["models"]["../foo"] = data["providers"]["codex"]["models"]["gpt-5.6-sol"]
        with self.assertRaisesRegex(RegistryError, "invalid format|parent path"):
            validate_registry(data, repo_root=ROOT)
        for field, value in (("binaryCandidates", []), ("routeFamilies", [])):
            data = json.loads(json.dumps(self.registry))
            if field == "binaryCandidates":
                data["providers"]["codex"][field] = value
            else:
                data["providers"]["opencode"][field][0]["patterns"] = value
            with self.assertRaisesRegex(RegistryError, "at least 1"):
                validate_registry(data, repo_root=ROOT)

    def test_positional_default_must_not_have_fallback(self) -> None:
        data = json.loads(json.dumps(self.registry))
        data["providers"]["opencode"]["defaultModel"]["fallback"] = "unexpected"
        with self.assertRaisesRegex(RegistryError, "null fallback"):
            validate_registry(data, repo_root=ROOT)

    def test_native_ownership_must_be_reciprocal(self) -> None:
        data = json.loads(json.dumps(self.registry))
        data["hosts"]["claude"]["nativeProviders"] = ["grok"]
        with self.assertRaisesRegex(RegistryError, "disagree"):
            validate_registry(data, repo_root=ROOT)

    def test_runtime_reference_anchor_must_exist(self) -> None:
        data = json.loads(json.dumps(self.registry))
        data["providers"]["codex"]["models"]["gpt-5.6-sol"]["runtimeReference"] = (
            "references/model-prompting.md#missing-anchor"
        )
        with self.assertRaisesRegex(RegistryError, "anchor does not exist"):
            validate_registry(data, repo_root=ROOT)

    def test_registry_paths_must_remain_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as outside:
            data = json.loads(json.dumps(self.registry))
            data["hosts"]["copilot"]["packagePath"] = f"../{Path(outside).name}"
            with self.assertRaisesRegex(RegistryError, "escapes the repository"):
                validate_registry(data, repo_root=ROOT)

        with tempfile.NamedTemporaryFile(dir=ROOT.parent, delete=False) as handle:
            outside_file = Path(handle.name)
        try:
            data = json.loads(json.dumps(self.registry))
            data["providers"]["codex"]["models"]["gpt-5.6-sol"]["promptReference"] = f"../{outside_file.name}"
            with self.assertRaisesRegex(RegistryError, "escapes the repository"):
                validate_registry(data, repo_root=ROOT)
        finally:
            outside_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
