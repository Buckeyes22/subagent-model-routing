"""Tests for the local, non-discovery doctor report."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing import doctor  # noqa: E402


class DoctorTests(unittest.TestCase):
    def environment(self, root: Path, *, providers: bool = True) -> dict[str, str]:
        home = root / "home"
        binary_dir = root / "bin"
        home.mkdir(exist_ok=True)
        binary_dir.mkdir(exist_ok=True)
        if providers:
            for name in ("codex", "claude", "grok", "kimi", "opencode"):
                path = binary_dir / name
                path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                path.chmod(0o755)
        return {
            "HOME": str(home),
            "PATH": f"{binary_dir}:{os.environ.get('PATH', '')}",
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CONFIG_HOME": str(root / "config"),
        }

    @staticmethod
    def completed(argv: list[str], *, help_complete: bool = True) -> subprocess.CompletedProcess[bytes]:
        if argv[-1] == "--version":
            output = f"{Path(argv[0]).name} 1.0\n".encode()
        elif "--help" in argv:
            flags = "exec --skip-git-repo-check --no-session-persistence --output-format --no-auto-update --format --prompt doctor provider"
            output = (flags if help_complete else "minimal help").encode()
        else:
            output = b"authenticated\n"
        return subprocess.CompletedProcess(argv, 0, output, b"")

    def test_default_report_is_serializable_non_mutating_and_avoids_live_probes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = self.environment(root)
            commands: list[list[str]] = []

            def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
                commands.append(argv)
                return self.completed(argv)

            with mock.patch.object(doctor.subprocess, "run", side_effect=runner):
                report = doctor.run_doctor(ROOT, env)
            json.dumps(report)
            self.assertEqual(1, report["schemaVersion"])
            self.assertEqual({"pass", "warn", "fail", "skip"}, set(report["summary"]))
            self.assertTrue(all(check["status"] in doctor.VALID_STATUSES for check in report["checks"]))
            self.assertTrue(commands)
            self.assertTrue(all("models" not in argv and "auth" not in argv and "login" not in argv for argv in commands))
            self.assertTrue(any(argv[-2:] == ["doctor", "config"] for argv in commands))
            self.assertFalse((root / "state").exists())
            self.assertFalse((root / "config").exists())
            security = next(
                check for check in report["checks"]
                if check["id"] == "security.unrestricted_mode"
            )
            self.assertEqual("WARN", security["status"])
            self.assertIn("default is unrestricted", security["summary"])
            self.assertIn("=0", security["remediation"])

    def test_explicit_restricted_mode_is_the_only_restricted_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(Path(directory))
            env["SUBAGENT_MODEL_ROUTING_UNRESTRICTED"] = "0"
            with mock.patch.object(
                doctor.subprocess,
                "run",
                side_effect=lambda argv, **_: self.completed(argv),
            ):
                report = doctor.run_doctor(ROOT, env)
            security = next(
                check for check in report["checks"]
                if check["id"] == "security.unrestricted_mode"
            )
            self.assertEqual("PASS", security["status"])
            self.assertIn("=0", security["summary"])

    def test_provider_filter_keeps_only_requested_provider_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(Path(directory))
            with mock.patch.object(doctor.subprocess, "run", side_effect=lambda argv, **_: self.completed(argv)):
                report = doctor.run_doctor(ROOT, env, provider="codex")
            providers = {check.get("provider") for check in report["checks"] if check["category"] == "provider"}
            self.assertEqual({"codex"}, providers)
            self.assertIn("runtime", {check["category"] for check in report["checks"]})

    def test_invalid_registry_is_machine_distinguishable_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config/provider-registry.json").write_text("{not-json", encoding="utf-8")
            report = doctor.run_doctor(root, self.environment(root, providers=False))
            self.assertEqual("fail", report["status"])
            self.assertEqual("runtime.registry_present", report["checks"][0]["id"])
            self.assertEqual("FAIL", report["checks"][0]["status"])

    def test_missing_binary_and_help_drift_are_warnings_not_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = self.environment(root)
            env["CODEX_BIN"] = str(root / "missing-codex")
            with mock.patch.object(doctor.subprocess, "run", side_effect=lambda argv, **_: self.completed(argv, help_complete=False)):
                report = doctor.run_doctor(ROOT, env)
            by_id = {check["id"]: check for check in report["checks"]}
            self.assertEqual("WARN", by_id["provider.codex.binary_resolved"]["status"])
            self.assertEqual("WARN", by_id["provider.claude.cli_contract"]["status"])

    def test_installation_only_has_runtime_checks_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(Path(directory), providers=False)
            with mock.patch.object(doctor.subprocess, "run", side_effect=lambda argv, **_: self.completed(argv)):
                report = doctor.run_doctor(ROOT, env, installation_only=True)
            self.assertEqual({"runtime"}, {check["category"] for check in report["checks"]})

    def test_live_auth_is_the_only_mode_that_runs_documented_auth_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(Path(directory))
            commands: list[list[str]] = []

            def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
                commands.append(argv)
                return self.completed(argv)

            with mock.patch.object(doctor.subprocess, "run", side_effect=runner):
                doctor.run_doctor(ROOT, env, provider="claude")
                self.assertFalse(any(argv[-2:] == ["auth", "status"] for argv in commands))
                doctor.run_doctor(ROOT, env, provider="claude", live_auth=True)
            self.assertTrue(any(argv[-2:] == ["auth", "status"] for argv in commands))
            self.assertFalse(any("models" in argv or "discover" in argv for argv in commands))

    def test_kimi_config_probe_is_read_only_bounded_to_status_and_does_not_retain_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(Path(directory))

            def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
                if argv[-2:] == ["doctor", "config"]:
                    return subprocess.CompletedProcess(
                        argv,
                        0,
                        b"OK config with sk-secret-that-must-not-be-retained\n",
                        b"private diagnostic detail\n",
                    )
                return self.completed(argv)

            with mock.patch.object(doctor.subprocess, "run", side_effect=runner):
                report = doctor.run_doctor(ROOT, env, provider="kimi")
            check = next(
                item for item in report["checks"]
                if item["id"] == "provider.kimi.config_probe"
            )
            self.assertEqual("PASS", check["status"])
            serialized = json.dumps(check)
            self.assertNotIn("sk-secret", serialized)
            self.assertNotIn("private diagnostic", serialized)
            self.assertEqual(["doctor", "config"], check["details"]["argv"][-2:])

    def test_unknown_provider_is_an_invocation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unknown provider"):
                doctor.run_doctor(ROOT, self.environment(Path(directory)), provider="unknown")

    def test_discovery_runs_only_when_explicit_and_is_provider_filterable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(Path(directory))
            discovered = [{
                "id": "provider.codex.models_discovery",
                "category": "provider",
                "provider": "codex",
                "status": "PASS",
                "summary": "models discovered",
                "details": {"source": "local-cache", "command": None, "models": ["gpt-test"], "configuredModels": []},
            }]
            with mock.patch.object(doctor.subprocess, "run", side_effect=lambda argv, **_: self.completed(argv)), mock.patch.object(
                doctor, "run_model_discovery", return_value=discovered
            ) as discovery:
                default = doctor.run_doctor(ROOT, env, provider="codex")
                discovery.assert_not_called()
                report = doctor.run_doctor(ROOT, env, provider="codex", discover_models=True)
            self.assertFalse(default["modes"]["discoverModels"])
            self.assertTrue(report["modes"]["discoverModels"])
            discovery.assert_called_once_with(ROOT, env, mock.ANY, provider="codex")
            self.assertEqual("PASS", next(check for check in report["checks"] if check["id"].endswith("models_discovery"))["status"])

    def test_installation_only_rejects_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "cannot be combined"):
                doctor.run_doctor(
                    ROOT,
                    self.environment(Path(directory)),
                    installation_only=True,
                    discover_models=True,
                )


if __name__ == "__main__":
    unittest.main()
