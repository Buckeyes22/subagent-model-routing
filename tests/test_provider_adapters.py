"""Provider adapters own provider-specific argv and environment only."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.providers import adapter_ids, get_adapter  # noqa: E402
from model_routing.errors import UsageError  # noqa: E402


class ProviderAdapterTests(unittest.TestCase):
    def test_registry_and_adapter_ids_match(self) -> None:
        self.assertEqual({"codex", "claude", "grok", "kimi", "opencode"}, adapter_ids())

    def test_codex_model_and_environment(self) -> None:
        adapter = get_adapter("codex")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            (home / ".codex/config.toml").write_text('model = "configured"\n', encoding="utf-8")
            request = adapter.parse(["prompt.md", "--model=gpt-test"], {}, home)
            prepared = adapter.prepare(
                request,
                "/bin/codex",
                b"prompt\n",
                {"OTEL_RESOURCE_ATTRIBUTES": "service.name=test"},
                {},
            )
        self.assertEqual("gpt-test", request.model)
        self.assertEqual(b"prompt\n", prepared.stdin)
        self.assertEqual("service.name=test,gen_ai.request.model=gpt-test", prepared.env["OTEL_RESOURCE_ATTRIBUTES"])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", prepared.argv)

    def test_claude_and_grok_keep_prompt_on_argv(self) -> None:
        cases = {
            "claude": (["prompt.md", "--model", "opus"], "opus", "--", "prompt"),
            "grok": (["prompt.md", "-m=grok-test"], "grok-test", "-p", "prompt"),
        }
        for provider, (argv, model, marker, prompt) in cases.items():
            with self.subTest(provider=provider):
                adapter = get_adapter(provider)
                request = adapter.parse(argv, {}, Path("/tmp"))
                prepared = adapter.prepare(request, f"/bin/{provider}", b"prompt\n\n", {}, {})
                self.assertEqual(model, request.model)
                self.assertIsNone(prepared.stdin)
                self.assertEqual(prompt, prepared.argv[prepared.argv.index(marker) + 1])

    def test_kimi_uses_configured_model_and_noninteractive_prompt_mode(self) -> None:
        adapter = get_adapter("kimi")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".kimi-code"
            config.mkdir()
            (config / "config.toml").write_text('default_model = "kimi-code/k3"\n', encoding="utf-8")
            request = adapter.parse(["prompt.md"], {}, home)
            prepared = adapter.prepare(
                request,
                "/bin/kimi",
                b"prompt\n\n",
                {"KIMI_DISABLE_TELEMETRY": "1"},
                {},
            )
        self.assertEqual("kimi-code/k3", request.model)
        self.assertIsNone(prepared.stdin)
        self.assertEqual("prompt", prepared.argv[prepared.argv.index("--prompt") + 1])
        self.assertEqual("text", prepared.argv[prepared.argv.index("--output-format") + 1])
        self.assertNotIn("--yolo", prepared.argv)
        self.assertNotIn("--auto", prepared.argv)
        self.assertEqual("1", prepared.env["KIMI_CODE_NO_AUTO_UPDATE"])
        self.assertEqual("1", prepared.env["KIMI_DISABLE_TELEMETRY"])

    def test_kimi_environment_model_precedes_config_and_cli_override_precedes_both(self) -> None:
        adapter = get_adapter("kimi")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".kimi-code"
            config.mkdir()
            (config / "config.toml").write_text(
                'default_model = "configured-model"\n', encoding="utf-8"
            )
            environment = {"KIMI_MODEL_NAME": "environment-model"}
            from_environment = adapter.parse(["prompt.md"], environment, home)
            from_cli = adapter.parse(
                ["prompt.md", "--model", "explicit-model"], environment, home
            )
        self.assertEqual("environment-model", from_environment.model)
        self.assertEqual("explicit-model", from_cli.model)

    def test_kimi_rejects_prompt_mode_conflicts_and_shim_owned_flags(self) -> None:
        adapter = get_adapter("kimi")
        for flag in (
            "-y",
            "--yolo",
            "--auto",
            "-p",
            "--prompt=other",
            "--output-format",
            "--output-format=stream-json",
        ):
            with self.subTest(flag=flag), self.assertRaises(UsageError):
                adapter.parse(["prompt.md", flag], {}, Path("/tmp"))

    def test_restricted_provider_flags(self) -> None:
        env = {"SUBAGENT_MODEL_ROUTING_UNRESTRICTED": "0"}
        codex = get_adapter("codex")
        request = codex.parse(["prompt.md"], env, Path("/tmp"))
        prepared = codex.prepare(request, "codex", b"prompt", env, {})
        self.assertEqual("workspace-write", prepared.argv[prepared.argv.index("--sandbox") + 1])
        for provider in ("claude", "grok", "kimi", "opencode"):
            adapter = get_adapter(provider)
            argv = ["provider/model", "prompt.md"] if provider == "opencode" else ["prompt.md"]
            request = adapter.parse(argv, env, Path("/tmp"))
            prepared = adapter.prepare(request, provider, b"prompt", env, {})
            self.assertNotIn("--dangerously-skip-permissions", prepared.argv)
            self.assertNotIn("--always-approve", prepared.argv)

    def test_binary_overrides_are_additive(self) -> None:
        expected = {
            "codex": ("CODEX_BIN", "/custom/codex"),
            "claude": ("CLAUDE_BIN", "/custom/claude"),
            "grok": ("GROK_BIN", "/custom/grok"),
            "kimi": ("KIMI_BIN", "/custom/kimi"),
            "opencode": ("OPENCODE_BIN", "/custom/opencode"),
        }
        for provider, (variable, path) in expected.items():
            with self.subTest(provider=provider):
                self.assertEqual(path, get_adapter(provider).resolve_binary({variable: path}, Path("/tmp")))

    def test_sanitized_arguments_redact_secret_values(self) -> None:
        adapter = get_adapter("codex")
        self.assertEqual(
            ["--api-key", "<redacted>", "--token=<redacted>", "--model=gpt-test"],
            adapter.sanitize_args(["--api-key", "secret-one", "--token=secret-two", "--model=gpt-test"]),
        )


if __name__ == "__main__":
    unittest.main()
