"""Portable hooks receive metadata on stdin and cannot pollute shim output."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.hooks import HookRunner, MAX_HOOK_OUTPUT_BYTES  # noqa: E402
from model_routing.run_store import RunStore  # noqa: E402


class HookTests(unittest.TestCase):
    def test_hook_receives_event_and_output_is_captured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "captured.json"
            env = {
                "HOME": directory,
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "HOOK_CAPTURE": str(capture),
            }
            config = root / "config/subagent-model-routing/hooks.json"
            config.parent.mkdir(parents=True)
            command = [
                sys.executable,
                "-c",
                "import os,sys,pathlib; pathlib.Path(os.environ['HOOK_CAPTURE']).write_bytes(sys.stdin.buffer.read()); print('hook-out')",
            ]
            config.write_text(json.dumps({"dispatch.failed": [{"command": command, "timeoutSeconds": 2}]}), encoding="utf-8")
            store = RunStore.create(env, "dispatch-one")
            event = {
                "event": "dispatch.failed",
                "dispatchId": "dispatch-one",
                "provider": "codex",
                "model": "gpt-test",
            }
            HookRunner(env)(event, store)
            self.assertEqual(event, json.loads(capture.read_text(encoding="utf-8")))
            hook_stdout = list(store.artifact("hooks").glob("*.stdout.log"))
            self.assertEqual(1, len(hook_stdout))
            self.assertEqual(b"hook-out\n", hook_stdout[0].read_bytes())

    def test_invalid_hook_config_is_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config/subagent-model-routing/hooks.json"
            config.parent.mkdir(parents=True)
            config.write_text("not-json", encoding="utf-8")
            env = {"HOME": directory, "XDG_STATE_HOME": str(root / "state"), "XDG_CONFIG_HOME": str(root / "config")}
            store = RunStore.create(env, "dispatch-one")
            HookRunner(env)({"event": "dispatch.failed", "dispatchId": "dispatch-one", "provider": "x", "model": "x"}, store)

    def test_hook_output_is_memory_bounded_and_reports_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {
                "HOME": directory,
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
            }
            config = root / "config/subagent-model-routing/hooks.json"
            config.parent.mkdir(parents=True)
            command = [
                sys.executable,
                "-c",
                "import os; os.write(1, b'x' * (2 * 1024 * 1024))",
            ]
            config.write_text(
                json.dumps({"dispatch.failed": [{"command": command}]}),
                encoding="utf-8",
            )
            store = RunStore.create(env, "dispatch-one")
            HookRunner(env)(
                {
                    "event": "dispatch.failed",
                    "dispatchId": "dispatch-one",
                    "provider": "codex",
                    "model": "gpt-test",
                },
                store,
            )
            stdout_path = next(store.artifact("hooks").glob("*.stdout.log"))
            status_path = next(store.artifact("hooks").glob("*.json"))
            self.assertEqual(MAX_HOOK_OUTPUT_BYTES, stdout_path.stat().st_size)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(2 * 1024 * 1024, status["stdoutBytes"])
            self.assertTrue(status["stdoutTruncated"])

    def test_invalid_hook_depth_is_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config/subagent-model-routing/hooks.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"dispatch.created": [{"command": ["/bin/true"]}]}), encoding="utf-8")
            env = {
                "HOME": directory,
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "SUBAGENT_MODEL_ROUTING_HOOK_DEPTH": "not-a-number",
            }
            store = RunStore.create(env, "dispatch-one")
            HookRunner(env)({"event": "dispatch.created", "dispatchId": "dispatch-one", "provider": "x", "model": "x"}, store)


if __name__ == "__main__":
    unittest.main()
