"""Tests for the explicit model-discovery backend used by `model-routing doctor --discover-models`.

This module imports `model_routing.discovery`, which must remain free of
import-time probes or filesystem writes. Each test exercises one observable
behavior and asserts the JSON-friendly check shape.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

# Imported lazily inside the import-side-effect test so the module reload can
# succeed even if discovery.py has not been authored yet.
from model_routing import discovery  # noqa: E402


REGISTRY: dict[str, object] = {
    "providers": {
        "opencode": {
            "models": {
                "kimi-for-coding/k2p7": {},
                "zai-coding-plan/glm-5.2": {},
            }
        },
        "codex": {
            "models": {
                "gpt-5.6-sol": {},
                "gpt-5.6-terra": {},
            }
        },
        "claude": {
            "models": {
                "sonnet": {},
                "opus": {},
            }
        },
        "grok": {
            "models": {
                "grok-4.5": {},
            }
        },
        "kimi": {
            "models": {
                "kimi-code/kimi-for-coding": {},
            }
        },
    }
}


def _make_home(root: Path, *, name: str = "home") -> Path:
    home = root / name
    home.mkdir(exist_ok=True)
    return home


class DiscoveryImportTests(unittest.TestCase):
    """Importing the module must perform no probes, no subprocesses, and no writes."""

    def test_importing_discovery_writes_no_files_under_repo_or_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory) / "repo"
            home = _make_home(Path(directory), name="home")
            repo_root.mkdir()
            env = {
                "HOME": str(home),
                "PATH": "/bin",
                "CODEX_HOME": str(home / "codex"),
            }
            with mock.patch.object(
                discovery, "run_bounded_capture"
            ) as run, mock.patch.object(
                discovery, "_resolve_codex_cache_path"
            ) as cache_resolver:
                cache_resolver.return_value = home / "codex" / "models_cache.json"
                discovery.discover_models(repo_root, env, REGISTRY, provider="opencode")
            run.assert_not_called()
            cache_resolver.assert_not_called()
            for child in repo_root.iterdir():
                self.fail(f"import or call produced files under repo: {child}")
            self.assertFalse((home / "codex").exists())
            self.assertFalse((home / ".codex").exists())

    def test_no_module_level_subprocess_invocation_on_import(self) -> None:
        with tempfile.TemporaryDirectory():
            with mock.patch(
                "subprocess.Popen"
            ) as run, mock.patch.object(
                discovery.os, "fork"
            ) as fork:
                run.reset_mock()
                fork.reset_mock()
                if "model_routing.discovery" in sys.modules:
                    del sys.modules["model_routing.discovery"]
                reloaded = __import__("importlib").import_module(
                    "model_routing.discovery"
                )
                self.assertIsNotNone(reloaded)
                self.assertTrue(hasattr(reloaded, "discover_models"))
            self.assertFalse(
                run.called,
                msg=f"subprocess.run invoked at import time: {run.call_args_list}",
            )
            self.assertFalse(
                fork.called,
                msg=f"os.fork invoked at import time: {fork.call_args_list}",
            )


class DiscoveryShapeTests(unittest.TestCase):
    """Every check returned by `discover_models` has the JSON-friendly shape."""

    def assert_valid_check(self, check: dict[str, object]) -> None:
        self.assertEqual("provider", check["category"])
        self.assertIn(check["status"], ("PASS", "WARN", "SKIP"))
        self.assertNotEqual(
            "FAIL",
            check["status"],
            msg="discovery backend must never emit FAIL",
        )
        self.assertIsInstance(check["id"], str) and check["id"]
        self.assertIsInstance(check["provider"], str)
        self.assertIsInstance(check["summary"], str) and check["summary"]
        details = check["details"]
        self.assertIsInstance(details, dict)
        self.assertIn("source", details)
        self.assertIn("command", details)
        self.assertIn("models", details)
        self.assertIn("configuredModels", details)
        self.assertIsInstance(details["models"], list)
        self.assertIsInstance(details["configuredModels"], list)
        for identifier in details["models"] + details["configuredModels"]:
            self.assertIsInstance(identifier, str)

    def test_all_checks_share_required_shape_across_providers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = _make_home(Path(directory))
            env = {"HOME": str(home), "PATH": "/bin"}
            checks = discovery.discover_models(
                Path(directory) / "repo", env, REGISTRY
            )
        self.assertEqual(5, len(checks))
        for check in checks:
            with self.subTest(provider=check["provider"]):
                self.assert_valid_check(check)


class OpenCodeDiscoveryTests(unittest.TestCase):
    def environment(self, *, root: Path, binary_path: Path | None) -> dict[str, str]:
        env = {
            "HOME": str(root / "home"),
            "PATH": str(binary_path.parent) if binary_path else "/nonexistent",
        }
        return env

    def completed(
        self,
        argv: list[str],
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    def test_opencode_success_parses_models_from_plain_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            stdout = b"minimax/MiniMax-M3\nkimi-for-coding/k2p7\nzai-coding-plan/glm-5.2\n"
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=self.completed(
                    [str(binary), "models"], stdout=stdout
                ),
            ) as run:
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            run.assert_called_once()
            argv, kwargs = run.call_args[0], run.call_args[1]
            self.assertEqual([str(binary), "models"], list(argv[0]))
            self.assertEqual(20.0, kwargs.get("timeout_seconds"))
            self.assertEqual(discovery.MAX_OUTPUT_BYTES, kwargs.get("max_bytes"))
            self.assertEqual(1, len(checks))
            check = checks[0]
            self.assertEqual("provider", check["category"])
            self.assertEqual("opencode", check["provider"])
            self.assertEqual("PASS", check["status"])
            self.assertEqual(
                ["kimi-for-coding/k2p7", "minimax/MiniMax-M3", "zai-coding-plan/glm-5.2"],
                check["details"]["models"],
            )
            self.assertEqual(
                ["kimi-for-coding/k2p7", "zai-coding-plan/glm-5.2"],
                check["details"]["configuredModels"],
            )
            self.assertEqual([str(binary), "models"], check["details"]["command"])
            self.assertEqual("live-opencode", check["details"]["source"])
            self.assertNotIn("api-key", repr(check["details"]).lower())

    def test_opencode_success_parses_models_from_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            payload = json.dumps(
                {"models": [{"id": "kimi-for-coding/k2p7"}, {"slug": "minimax/MiniMax-M3"}]}
            ).encode()
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=self.completed([str(binary), "models"], stdout=payload),
            ):
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            self.assertEqual("PASS", checks[0]["status"])
            self.assertEqual(
                ["kimi-for-coding/k2p7", "minimax/MiniMax-M3"],
                checks[0]["details"]["models"],
            )

    def test_opencode_timeout_returns_warn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=mock.Mock(
                    returncode=124,
                    stdout=b"",
                    stderr=b"",
                    timed_out=True,
                ),
            ):
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            self.assertEqual("WARN", checks[0]["status"])
            self.assertEqual("live-opencode", checks[0]["details"]["source"])
            self.assertEqual([], checks[0]["details"]["models"])

    def test_opencode_nonzero_exit_returns_warn_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=self.completed(
                    [str(binary), "models"], returncode=1, stderr=b"denied"
                ),
            ):
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            self.assertEqual("WARN", checks[0]["status"])
            self.assertEqual([], checks[0]["details"]["models"])
            self.assertEqual([str(binary), "models"], checks[0]["details"]["command"])

    def test_opencode_output_drift_returns_warn_not_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=self.completed(
                    [str(binary), "models"], stdout=b"this output has no model identifiers\n"
                ),
            ):
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            self.assertEqual("WARN", checks[0]["status"])
            self.assertEqual([], checks[0]["details"]["models"])

    def test_opencode_output_is_capped_at_one_mebibyte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            line = b"kimi-for-coding/k2p7 extra detail " + b"x" * 1024 + b"\n"
            huge_stdout = line * (2 * 1024)  # well above 1 MiB
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=self.completed(
                    [str(binary), "models"], stdout=huge_stdout
                ),
            ) as run:
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            kwargs = run.call_args[1]
            self.assertIsNotNone(kwargs.get("timeout_seconds"))
            self.assertEqual(discovery.MAX_OUTPUT_BYTES, kwargs.get("max_bytes"))
            self.assertLess(len(huge_stdout), 8 * 1024 * 1024)  # sanity guard
            models = checks[0]["details"]["models"]
            self.assertTrue(models, msg="huge output truncated to 1 MiB still yields a model")
            self.assertLessEqual(
                len(json.dumps(checks[0]).encode()),  # full result is small
                2 * 1024 * 1024,
            )

    def test_opencode_missing_binary_is_warn_with_null_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/nonexistent"}
            with mock.patch.object(discovery, "run_bounded_capture") as run:
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            run.assert_not_called()
            self.assertEqual("WARN", checks[0]["status"])
            self.assertIsNone(checks[0]["details"]["command"])
            self.assertEqual("live-opencode", checks[0]["details"]["source"])
            self.assertEqual([], checks[0]["details"]["models"])

    def test_opencode_binary_override_env_is_honored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            overrides = root / "overrides"
            overrides.mkdir()
            binary = overrides / "custom-opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": "/nonexistent", "OPENCODE_BIN": str(binary)}
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=self.completed(
                    [str(binary), "models"], stdout=b"kimi-for-coding/k2p7\n"
                ),
            ) as run:
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            argv, _kwargs = run.call_args[0], run.call_args[1]
            self.assertEqual([str(binary), "models"], list(argv[0]))
            self.assertEqual("PASS", checks[0]["status"])


class KimiDiscoveryTests(unittest.TestCase):
    def test_kimi_discovers_configured_aliases_without_retaining_raw_provider_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "kimi"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {
                "HOME": str(home),
                "PATH": str(binary_dir),
                "KIMI_MODEL_NAME": "temporary-model",
            }
            payload = {
                "providers": {
                    "managed:kimi-code": {
                        "api_key": "sk-secret-do-not-retain",
                        "custom_headers": {"Authorization": "Bearer private"},
                    }
                },
                "models": {
                    "kimi-code/kimi-for-coding": {"provider": "managed:kimi-code"},
                    "plainalias": {"provider": "managed:kimi-code"},
                },
            }
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=subprocess.CompletedProcess(
                    [str(binary), "provider", "list", "--json"],
                    0,
                    json.dumps(payload).encode(),
                    b"stderr private detail",
                ),
            ) as run:
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="kimi"
                )
            check = checks[0]
            self.assertEqual("PASS", check["status"])
            self.assertEqual("live-kimi-config", check["details"]["source"])
            self.assertEqual(
                ["kimi-code/kimi-for-coding", "plainalias", "temporary-model"],
                check["details"]["models"],
            )
            self.assertEqual(
                [str(binary), "provider", "list", "--json"],
                check["details"]["command"],
            )
            serialized = json.dumps(check)
            for forbidden in (
                "sk-secret",
                "Bearer private",
                "stderr private",
                "api_key",
                "Authorization",
            ):
                self.assertNotIn(forbidden, serialized)
            run.assert_called_once_with(
                [str(binary), "provider", "list", "--json"],
                env=env,
                timeout_seconds=discovery.KIMI_TIMEOUT,
                max_bytes=discovery.MAX_OUTPUT_BYTES,
            )

    def test_kimi_malformed_inventory_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "kimi"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=subprocess.CompletedProcess(
                    [str(binary), "provider", "list", "--json"],
                    0,
                    b"not-json and sk-secret",
                    b"",
                ),
            ):
                check = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="kimi"
                )[0]
            self.assertEqual("WARN", check["status"])
            self.assertEqual([], check["details"]["models"])
            self.assertNotIn("sk-secret", json.dumps(check))


class CodexCacheDiscoveryTests(unittest.TestCase):
    def write_cache(self, home: Path, payload: dict[str, object] | list[object]) -> Path:
        codex_home = home / "codex"
        codex_home.mkdir(exist_ok=True)
        cache_path = codex_home / "models_cache.json"
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return cache_path

    def test_codex_cache_as_list_with_id_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin", "CODEX_HOME": str(home / "codex")}
            self.write_cache(
                home,
                [
                    {"id": "gpt-5.6-sol"},
                    {"id": "gpt-5.6-terra"},
                    {"id": "gpt-5.6-sol"},  # duplicate
                ],
            )
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="codex"
            )
            self.assertEqual("PASS", checks[0]["status"])
            self.assertEqual(
                ["gpt-5.6-sol", "gpt-5.6-terra"], checks[0]["details"]["models"]
            )
            self.assertEqual("local-cache", checks[0]["details"]["source"])
            self.assertIsNone(checks[0]["details"]["command"])

    def test_codex_cache_as_object_with_models_array(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin", "CODEX_HOME": str(home / "codex")}
            self.write_cache(
                home,
                {
                    "models": [
                        {"slug": "gpt-5.6-sol"},
                        {"model": "gpt-5.6-terra"},
                    ]
                },
            )
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="codex"
            )
            self.assertEqual("PASS", checks[0]["status"])
            self.assertEqual(
                ["gpt-5.6-sol", "gpt-5.6-terra"], checks[0]["details"]["models"]
            )

    def test_codex_cache_falls_back_to_dot_codex_when_codex_home_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin"}
            codex_dir = home / ".codex"
            codex_dir.mkdir(exist_ok=True)
            (codex_dir / "models_cache.json").write_text(
                json.dumps({"models": [{"id": "gpt-5.6-sol"}]}), encoding="utf-8"
            )
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="codex"
            )
            self.assertEqual("PASS", checks[0]["status"])
            self.assertEqual(["gpt-5.6-sol"], checks[0]["details"]["models"])

    def test_codex_cache_missing_is_warn_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin", "CODEX_HOME": str(home / "codex")}
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="codex"
            )
            self.assertEqual("WARN", checks[0]["status"])
            self.assertEqual([], checks[0]["details"]["models"])

    def test_codex_cache_malformed_is_warn_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin", "CODEX_HOME": str(home / "codex")}
            self.write_cache(home, {"unexpected": "shape-only"})  # type: ignore[arg-type]
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="codex"
            )
            self.assertEqual("WARN", checks[0]["status"])
            self.assertEqual([], checks[0]["details"]["models"])

    def test_codex_cache_invalid_json_is_warn_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin", "CODEX_HOME": str(home / "codex")}
            cache_path = self.write_cache(home, [])  # type: ignore[arg-type]
            cache_path.write_text("{this is not json", encoding="utf-8")
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="codex"
            )
            self.assertEqual("WARN", checks[0]["status"])
            self.assertEqual([], checks[0]["details"]["models"])


class UnsupportedProviderTests(unittest.TestCase):
    def test_claude_is_skip_with_unsupported_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin"}
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="claude"
            )
            self.assertEqual("SKIP", checks[0]["status"])
            self.assertEqual("unsupported", checks[0]["details"]["source"])
            self.assertIsNone(checks[0]["details"]["command"])
            self.assertEqual(["opus", "sonnet"], checks[0]["details"]["models"])
            self.assertEqual(["opus", "sonnet"], checks[0]["details"]["configuredModels"])

    def test_grok_is_skip_with_unsupported_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin"}
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="grok"
            )
            self.assertEqual("SKIP", checks[0]["status"])
            self.assertEqual("unsupported", checks[0]["details"]["source"])
            self.assertIsNone(checks[0]["details"]["command"])
            self.assertEqual(["grok-4.5"], checks[0]["details"]["configuredModels"])
            self.assertEqual(["grok-4.5"], checks[0]["details"]["models"])

    def test_unsupported_provider_does_not_invoke_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin"}
            with mock.patch.object(discovery, "run_bounded_capture") as run:
                discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="claude"
                )
            run.assert_not_called()


class ProviderFilterTests(unittest.TestCase):
    def test_unfiltered_returns_all_providers_in_sorted_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin"}
            checks = discovery.discover_models(root / "repo", env, REGISTRY)
            self.assertEqual(
                ["claude", "codex", "grok", "kimi", "opencode"],
                [check["provider"] for check in checks],
            )

    def test_filter_returns_exactly_one_provider_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            env = {"HOME": str(home), "PATH": "/bin"}
            checks = discovery.discover_models(
                root / "repo", env, REGISTRY, provider="opencode"
            )
            self.assertEqual(1, len(checks))
            self.assertEqual("opencode", checks[0]["provider"])
            self.assertEqual(
                "provider.opencode.models_discovery", checks[0]["id"]
            )

    def test_unknown_provider_filter_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = _make_home(Path(directory))
            env = {"HOME": str(home), "PATH": "/bin"}
            with self.assertRaises(ValueError):
                discovery.discover_models(
                    Path(directory) / "repo", env, REGISTRY, provider="unknown"
                )


class ModelSortingDedupTests(unittest.TestCase):
    def test_opencode_models_are_sorted_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            stdout = (
                b"zeta/9\nalpha/1\nbeta/2\nalpha/1\nbeta/2\n"
                b"minimax/MiniMax-M3\n"
            )
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=subprocess.CompletedProcess(
                    [str(binary), "models"], 0, stdout, b""
                ),
            ):
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            self.assertEqual(
                [
                    "alpha/1",
                    "beta/2",
                    "minimax/MiniMax-M3",
                    "zeta/9",
                ],
                checks[0]["details"]["models"],
            )

    def test_invalid_identifiers_are_stripped_during_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": str(binary_dir)}
            stdout = b"!!!\n************\n   ???@@@\nnoisy conversational word\n"
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=subprocess.CompletedProcess(
                    [str(binary), "models"], 0, stdout, b""
                ),
            ):
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            self.assertEqual("WARN", checks[0]["status"])
            self.assertEqual([], checks[0]["details"]["models"])


class SecretRetentionTests(unittest.TestCase):
    def test_opencode_does_not_leak_raw_output_env_or_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _make_home(root)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            env = {
                "HOME": str(home),
                "PATH": str(binary_dir),
                "OPENCODE_API_KEY": "sk-test-secret-do-not-leak",
                "OPENCODE_BIN": str(binary),
            }
            stdout_blob = b"kimi-for-coding/k2p7 -----BEGIN RAW LINE-----\nthis is part of stdout"
            serialized = json.dumps(stdout_blob.decode())
            with mock.patch.object(
                discovery,
                "run_bounded_capture",
                return_value=subprocess.CompletedProcess(
                    [str(binary), "models"], 0, stdout_blob, b""
                ),
            ):
                checks = discovery.discover_models(
                    root / "repo", env, REGISTRY, provider="opencode"
                )
            check = checks[0]
            details_repr = json.dumps(check)
            self.assertNotIn("sk-test-secret", details_repr)
            self.assertNotIn("OPENCODE_API_KEY", details_repr)
            self.assertNotIn("BEGIN RAW LINE", details_repr)
            self.assertNotIn("this is part of stdout", details_repr)
            self.assertNotIn(serialized, details_repr)
            self.assertNotIn(stdout_blob.decode(), details_repr)
            self.assertNotIn("env", details_repr)
            self.assertNotIn("PATH", details_repr)
            self.assertNotIn("HOME", details_repr)
            self.assertNotIn("secret", details_repr.lower())
            self.assertNotIn("api_key", details_repr.lower())
            self.assertNotIn("password", details_repr.lower())
            self.assertNotIn("authorization", details_repr.lower())
            self.assertEqual(
                {"source", "command", "models", "configuredModels"},
                set(check["details"].keys()),
            )


if __name__ == "__main__":
    unittest.main()
