"""Golden characterization tests for the v0.2 public shim behavior."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import unittest

from tests.shim_test_support import SHIMS, ShimSandbox


PROVIDER_ARGS = {
    "codex": lambda prompt: [str(prompt)],
    "claude": lambda prompt: [str(prompt)],
    "grok": lambda prompt: [str(prompt)],
    "kimi": lambda prompt: [str(prompt)],
    "opencode": lambda prompt: ["test-provider/test-model", str(prompt)],
}


class ShimContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandboxes: list[ShimSandbox] = []

    def tearDown(self) -> None:
        for sandbox in self.sandboxes:
            sandbox.cleanup()

    def sandbox(self, *, include_timeout: bool = True) -> ShimSandbox:
        sandbox = ShimSandbox(include_timeout=include_timeout)
        self.sandboxes.append(sandbox)
        return sandbox

    def test_usage_errors_emit_only_plain_sentinel_and_no_ledger(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                result = sandbox.run(shim, [])
                self.assertEqual(64, result.returncode)
                self.assertEqual(b"SHIM-DONE exit=64\n", result.stdout)
                self.assertEqual([], sandbox.ledger_records())

    def test_kimi_prompt_mode_conflicts_are_usage_errors_before_provider_start(self) -> None:
        for flag in ("-y", "--yolo", "--auto", "-p", "--prompt=other", "--output-format=stream-json"):
            with self.subTest(flag=flag):
                sandbox = self.sandbox()
                sandbox.install_provider("kimi")
                prompt = sandbox.prompt()
                result = sandbox.run("kimi", [str(prompt), flag])
                self.assertEqual(64, result.returncode)
                self.assertEqual(b"SHIM-DONE exit=64\n", result.stdout)
                self.assertEqual([], sandbox.ledger_records())
                self.assertEqual([], sandbox.captured_args())

    def test_kimi_environment_model_attribution_and_cli_precedence(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("kimi")
        prompt = sandbox.prompt()
        environment = sandbox.environment(KIMI_MODEL_NAME="environment-model")
        result = sandbox.run("kimi", [str(prompt)], env=environment)
        self.assertEqual(0, result.returncode)
        self.assertEqual("environment-model", sandbox.ledger_records()[-1]["model"])

        explicit = sandbox.run(
            "kimi",
            [str(prompt), "--model", "explicit-model"],
            env=environment,
        )
        self.assertEqual(0, explicit.returncode)
        self.assertEqual("explicit-model", sandbox.ledger_records()[-1]["model"])

    def test_missing_timeout_emits_plain_127_sentinel_and_no_ledger(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox(include_timeout=False)
                if shim != "codex":
                    sandbox.install_provider(shim)
                prompt = sandbox.prompt()
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt))
                self.assertEqual(127, result.returncode)
                self.assertEqual(b"SHIM-DONE exit=127\n", result.stdout)
                self.assertEqual([], sandbox.ledger_records())

    def test_missing_provider_binary_preserves_per_shim_ledger_asymmetry(self) -> None:
        expected_events = {
            "codex": ["started", "finished"],
            "claude": [],
            "grok": [],
            "kimi": [],
            "opencode": ["finished"],
        }
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                prompt = sandbox.prompt()
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt))
                self.assertEqual(127, result.returncode)
                expected_stdout = (
                    b"\nSHIM-DONE exit=127\n" if shim == "codex" else b"SHIM-DONE exit=127\n"
                )
                self.assertEqual(expected_stdout, result.stdout)
                records = sandbox.ledger_records()
                self.assertEqual(expected_events[shim], [record["event"] for record in records])
                if records and records[-1]["event"] == "finished":
                    self.assertEqual(127, records[-1]["exit"])
                    self.assertEqual("error", records[-1]["outcome"])

    def test_unreadable_prompt_preserves_started_ordering(self) -> None:
        expected_events = {
            "codex": ["started", "finished"],
            "claude": ["finished"],
            "grok": ["finished"],
            "kimi": ["finished"],
            "opencode": ["started", "finished"],
        }
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                missing = sandbox.root / "missing-prompt.md"
                result = sandbox.run(shim, PROVIDER_ARGS[shim](missing))
                self.assertEqual(66, result.returncode)
                self.assertEqual(b"SHIM-DONE exit=66\n", result.stdout)
                records = sandbox.ledger_records()
                self.assertEqual(expected_events[shim], [record["event"] for record in records])
                terminal = records[-1]
                self.assertEqual(66, terminal["exit"])
                self.assertEqual(0, terminal["wall_s"])
                self.assertEqual("error", terminal["outcome"])

    def test_success_records_started_shape_and_exact_sentinel_suffix(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                prompt = sandbox.prompt()
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt))
                self.assertEqual(0, result.returncode)
                self.assertTrue(result.stdout.endswith(b"fake-provider\n\nSHIM-DONE exit=0\n"))
                records = sandbox.ledger_records()
                self.assertEqual(["started", "finished"], [record["event"] for record in records])
                started = records[0]
                for absent in ("exit", "wall_s", "outcome"):
                    self.assertNotIn(absent, started)
                self.assertEqual(0, records[1]["exit"])
                self.assertEqual("ok", records[1]["outcome"])

    def test_prompt_delivery_matches_provider_contract(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                prompt_text = "prompt beginning with --help\nsecond line\n"
                prompt = sandbox.prompt(prompt_text)
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt))
                self.assertEqual(0, result.returncode)
                args = sandbox.captured_args()
                if shim in {"codex", "opencode"}:
                    self.assertEqual(prompt_text.encode(), sandbox.captured_stdin())
                    self.assertNotIn(prompt_text.rstrip("\n"), args)
                elif shim == "claude":
                    self.assertEqual([], sandbox.captured_stdin().splitlines())
                    self.assertEqual(["--", prompt_text.rstrip("\n")], args[-2:])
                elif shim == "kimi":
                    self.assertEqual([], sandbox.captured_stdin().splitlines())
                    self.assertEqual(prompt_text.rstrip("\n"), args[args.index("--prompt") + 1])
                else:
                    self.assertEqual([], sandbox.captured_stdin().splitlines())
                    self.assertEqual(prompt_text.rstrip("\n"), args[args.index("-p") + 1])

    def test_stdin_prompt_source_matches_file_delivery(self) -> None:
        prompt = b"stdin prompt\nsecond line\n"
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                args = ["test-provider/test-model", "-"] if shim == "opencode" else ["-"]
                result = sandbox.run(shim, args, input_bytes=prompt)
                self.assertEqual(0, result.returncode)
                captured_args = sandbox.captured_args()
                if shim in {"codex", "opencode"}:
                    self.assertEqual(prompt, sandbox.captured_stdin())
                elif shim == "claude":
                    self.assertEqual(prompt.decode().rstrip("\n"), captured_args[-1])
                elif shim == "kimi":
                    self.assertEqual(prompt.decode().rstrip("\n"), captured_args[captured_args.index("--prompt") + 1])
                else:
                    self.assertEqual(prompt.decode().rstrip("\n"), captured_args[captured_args.index("-p") + 1])

    def test_effective_model_parsing_forms_are_preserved(self) -> None:
        cases = {
            "codex": [
                (["-m", "gpt-a"], "gpt-a"),
                (["--model", "gpt-b"], "gpt-b"),
                (["--model=gpt-c"], "gpt-c"),
                (["-m=gpt-d"], "gpt-d"),
                (["model=gpt-e"], "gpt-e"),
            ],
            "claude": [
                (["--model", "opus"], "opus"),
                (["--model=fable"], "fable"),
            ],
            "grok": [
                (["-m", "grok-a"], "grok-a"),
                (["--model", "grok-b"], "grok-b"),
                (["-m=grok-c"], "grok-c"),
                (["--model=grok-d"], "grok-d"),
            ],
            "kimi": [
                (["-m", "kimi-a"], "kimi-a"),
                (["--model", "kimi-b"], "kimi-b"),
                (["-m=kimi-c"], "kimi-c"),
                (["--model=kimi-d"], "kimi-d"),
            ],
        }
        for shim, forms in cases.items():
            for forwarded, expected in forms:
                with self.subTest(shim=shim, forwarded=forwarded):
                    sandbox = self.sandbox()
                    sandbox.install_provider(shim)
                    prompt = sandbox.prompt()
                    result = sandbox.run(shim, [str(prompt), *forwarded])
                    self.assertEqual(0, result.returncode)
                    self.assertEqual(expected, sandbox.ledger_records()[-1]["model"])

        sandbox = self.sandbox()
        sandbox.install_provider("opencode")
        prompt = sandbox.prompt()
        result = sandbox.run("opencode", ["custom/provider-model", str(prompt)])
        self.assertEqual(0, result.returncode)
        self.assertEqual("custom/provider-model", sandbox.ledger_records()[-1]["model"])

    def test_restricted_policy_flags_are_preserved(self) -> None:
        expectations = {
            "codex": ("--sandbox", "workspace-write"),
            "claude": None,
            "grok": None,
            "kimi": None,
            "opencode": None,
        }
        forbidden = {
            "codex": "--dangerously-bypass-approvals-and-sandbox",
            "claude": "--dangerously-skip-permissions",
            "grok": "--always-approve",
            "kimi": "--yolo",
            "opencode": "--dangerously-skip-permissions",
        }
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                prompt = sandbox.prompt()
                env = sandbox.environment(SUBAGENT_MODEL_ROUTING_UNRESTRICTED="0")
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt), env=env)
                self.assertEqual(0, result.returncode)
                args = sandbox.captured_args()
                self.assertNotIn(forbidden[shim], args)
                if expectations[shim]:
                    flag, value = expectations[shim]
                    self.assertEqual(value, args[args.index(flag) + 1])

    def test_opencode_unrestricted_help_probe_supports_both_known_flags(self) -> None:
        for advertised in ("--dangerously-skip-permissions", "--auto"):
            with self.subTest(advertised=advertised):
                sandbox = self.sandbox()
                sandbox.install_provider("opencode")
                prompt = sandbox.prompt()
                env = sandbox.environment(FAKE_HELP=f"usage: opencode run {advertised}\n")
                result = sandbox.run(
                    "opencode",
                    ["test-provider/test-model", str(prompt)],
                    env=env,
                )
                self.assertEqual(0, result.returncode)
                self.assertIn(advertised, sandbox.captured_args())

    def test_exit_code_and_error_outcome_propagate(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                prompt = sandbox.prompt()
                env = sandbox.environment(FAKE_EXIT="7")
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt), env=env)
                self.assertEqual(7, result.returncode)
                self.assertTrue(result.stdout.endswith(b"\nSHIM-DONE exit=7\n"))
                terminal = sandbox.ledger_records()[-1]
                self.assertEqual(7, terminal["exit"])
                self.assertEqual("error", terminal["outcome"])

    def test_timeout_records_124_and_timeout_outcome(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                prompt = sandbox.prompt()
                env = sandbox.environment(FAKE_SLEEP_SECS="2", SHIM_TIMEOUT_SECS="1")
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt), env=env, timeout=5)
                self.assertEqual(124, result.returncode)
                terminal = sandbox.ledger_records()[-1]
                self.assertEqual(124, terminal["exit"])
                self.assertEqual("timeout", terminal["outcome"])
                self.assertTrue(terminal["supervisor_timeout"])

    def test_provider_exit_124_preserves_legacy_timeout_label_with_discriminator(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        result = sandbox.run("codex", [str(prompt)], env=sandbox.environment(FAKE_EXIT="124"))
        self.assertEqual(124, result.returncode)
        terminal = sandbox.ledger_records()[-1]
        self.assertEqual("timeout", terminal["outcome"])
        self.assertFalse(terminal["supervisor_timeout"])
        structured = json.loads((sandbox.run_directories()[0] / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("failed", structured["status"])
        self.assertEqual("error", structured["outcome"])

    def test_interrupted_run_leaves_orphaned_started_record(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        env = sandbox.environment(FAKE_SLEEP_SECS="30")
        process = subprocess.Popen(
            ["/bin/bash", str(SHIMS["codex"]), str(prompt)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                records = sandbox.ledger_records()
                if records:
                    break
                time.sleep(0.02)
            else:
                self.fail("shim did not append started record before deadline")
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            records = sandbox.ledger_records()
            self.assertEqual(["started"], [record["event"] for record in records])
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

    def test_telemetry_environment_mutations_are_preserved(self) -> None:
        codex = self.sandbox()
        codex.install_provider("codex")
        prompt = codex.prompt()
        result = codex.run(
            "codex",
            [str(prompt), "--model=gpt-telemetry"],
            env=codex.environment(OTEL_RESOURCE_ATTRIBUTES="service.name=test"),
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual(
            "service.name=test,gen_ai.request.model=gpt-telemetry",
            codex.captured_env()["OTEL_RESOURCE_ATTRIBUTES"],
        )

        opencode = self.sandbox()
        opencode.install_provider("opencode")
        prompt = opencode.prompt()
        result = opencode.run(
            "opencode",
            ["provider/model", str(prompt)],
            env=opencode.environment(OPENCODE_OTLP_ENDPOINT="http://collector:4318"),
        )
        self.assertEqual(0, result.returncode)
        captured = opencode.captured_env()
        self.assertEqual("1", captured["OPENCODE_ENABLE_TELEMETRY"])
        self.assertEqual("http/protobuf", captured["OPENCODE_OTLP_PROTOCOL"])
        self.assertEqual("http://collector:4318", captured["OPENCODE_OTLP_ENDPOINT"])
        self.assertEqual("service.name=opencode", captured["OPENCODE_RESOURCE_ATTRIBUTES"])

    def test_codex_binary_override_is_additive(self) -> None:
        sandbox = self.sandbox()
        custom = sandbox.install_provider("custom-codex")
        prompt = sandbox.prompt()
        result = sandbox.run("codex", [str(prompt)], env=sandbox.environment(CODEX_BIN=str(custom)))
        self.assertEqual(0, result.returncode)
        self.assertTrue(result.stdout.endswith(b"fake-provider\n\nSHIM-DONE exit=0\n"))
        self.assertEqual("codex-default", sandbox.ledger_records()[-1]["model"])

    def test_success_creates_private_structured_run_without_retaining_prompt(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                sandbox = self.sandbox()
                sandbox.install_provider(shim)
                prompt = sandbox.prompt("sensitive prompt\n")
                result = sandbox.run(shim, PROVIDER_ARGS[shim](prompt))
                self.assertEqual(0, result.returncode)
                run_directories = sandbox.run_directories()
                self.assertEqual(1, len(run_directories))
                run = run_directories[0]
                self.assertEqual(0o700, run.stat().st_mode & 0o777)
                self.assertFalse((run / "prompt.md").exists())
                request = json.loads((run / "request.json").read_text(encoding="utf-8"))
                terminal = json.loads((run / "result.json").read_text(encoding="utf-8"))
                events = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len("sensitive prompt\n"), request["promptSource"]["bytes"])
                self.assertEqual("succeeded", terminal["status"])
                self.assertEqual(0, terminal["exitCode"])
                self.assertEqual("dispatch.created", events[0]["event"])
                self.assertEqual("dispatch.succeeded", events[-1]["event"])
                for artifact in run.iterdir():
                    if artifact.is_file():
                        self.assertEqual(0o600, artifact.stat().st_mode & 0o777, artifact)

    def test_concurrent_dispatches_leave_parseable_ledger_lines(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        env = sandbox.environment()
        processes = [
            subprocess.Popen(
                ["/bin/bash", str(SHIMS["codex"]), str(prompt), f"--model=gpt-{index}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            for index in range(8)
        ]
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(0, process.returncode, stderr.decode(errors="replace"))
            self.assertTrue(stdout.endswith(b"SHIM-DONE exit=0\n"))
        raw_lines = sandbox.ledger.read_text(encoding="utf-8").splitlines()
        self.assertEqual(16, len(raw_lines))
        records = [json.loads(line) for line in raw_lines]
        self.assertEqual(8, sum(record["event"] == "started" for record in records))
        self.assertEqual(8, sum(record["event"] == "finished" for record in records))


if __name__ == "__main__":
    unittest.main()
