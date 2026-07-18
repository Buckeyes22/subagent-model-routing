"""Additive runtime behavior above the frozen v0.2 shim contract."""

from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

from tests.shim_test_support import SHIMS, ShimSandbox


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.dispatch import Lifecycle  # noqa: E402
from model_routing.events import EventEmitter  # noqa: E402
from model_routing.run_store import RunStore  # noqa: E402
from model_routing.result import validate_result  # noqa: E402


class DispatchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandboxes: list[ShimSandbox] = []

    def tearDown(self) -> None:
        for sandbox in self.sandboxes:
            sandbox.cleanup()

    def sandbox(self) -> ShimSandbox:
        value = ShimSandbox()
        self.sandboxes.append(value)
        return value

    def test_prompt_retention_is_explicit_and_runs_cli_can_inspect_it(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt("retained prompt\n")
        env = sandbox.environment()
        result = sandbox.run("codex", [str(prompt), "--routing-retain-prompt"], env=env)
        self.assertEqual(0, result.returncode)
        run = sandbox.run_directories()[0]
        self.assertEqual(b"retained prompt\n", (run / "prompt.md").read_bytes())

        listed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/model-routing"), "runs", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(0, listed.returncode)
        self.assertIn(run.name, listed.stdout.decode())
        shown = subprocess.run(
            [sys.executable, str(ROOT / "scripts/model-routing"), "runs", "show", run.name[:8]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual("succeeded", json.loads(shown.stdout)["status"])
        logs = subprocess.run(
            [sys.executable, str(ROOT / "scripts/model-routing"), "runs", "logs", run.name[:8], "--channel", "both"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(0, logs.returncode)
        self.assertEqual(b"fake-provider\n", logs.stdout)
        cleaned = subprocess.run(
            [sys.executable, str(ROOT / "scripts/model-routing"), "runs", "cleanup", "--all"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(0, cleaned.returncode)
        self.assertIn(run.name, cleaned.stdout.decode())
        self.assertEqual([], sandbox.run_directories())

    def test_direct_dispatch_command_uses_the_same_contract(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/model-routing"), "dispatch", "codex", str(prompt)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=sandbox.environment(),
            check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual(b"fake-provider\n\nSHIM-DONE exit=0\n", result.stdout)

    def test_isolated_dispatch_retains_changes_until_explicit_apply(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        repository = sandbox.root / "repository"
        repository.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Dispatch Tests"], cwd=repository, check=True)
        (repository / "base.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "base.txt"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repository, check=True)
        env = sandbox.environment(FAKE_WRITE_RELATIVE="generated.txt", FAKE_WRITE_CONTENT="isolated\n")

        dispatched = subprocess.run(
            [
                "/bin/bash", str(SHIMS["codex"]), str(prompt),
                "--routing-workspace", "isolated", "--routing-task-mode", "write",
            ],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(0, dispatched.returncode, dispatched.stderr.decode(errors="replace"))
        self.assertFalse((repository / "generated.txt").exists())
        run = sandbox.run_directories()[0]
        result = json.loads((run / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("isolated", result["workspace"]["mode"])
        self.assertTrue((run / "changes.patch").is_file())
        self.assertEqual("isolated\n", (Path(result["workspace"]["path"]) / "generated.txt").read_text(encoding="utf-8"))

        applied = subprocess.run(
            [sys.executable, str(ROOT / "scripts/model-routing"), "runs", "apply", run.name, "--target", str(repository)],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(0, applied.returncode, applied.stderr.decode(errors="replace"))
        self.assertEqual("isolated\n", (repository / "generated.txt").read_text(encoding="utf-8"))
        applied_result = json.loads((run / "result.json").read_text(encoding="utf-8"))
        validate_result(applied_result)
        self.assertEqual("succeeded", applied_result["status"])
        self.assertEqual("applied", applied_result["integration"]["status"])

    def test_auto_workspace_without_task_mode_is_a_usage_error(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        result = sandbox.run("codex", [str(prompt), "--routing-workspace", "auto"])
        self.assertEqual(64, result.returncode)
        self.assertEqual(b"SHIM-DONE exit=64\n", result.stdout)
        self.assertEqual([], sandbox.ledger_records())
        self.assertEqual([], sandbox.run_directories())

    def test_failed_isolated_provider_still_captures_useful_changes(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        repository = sandbox.root / "failed-repository"
        repository.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Dispatch Tests"], cwd=repository, check=True)
        (repository / "base.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "base.txt"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repository, check=True)
        env = sandbox.environment(FAKE_WRITE_RELATIVE="partial.txt", FAKE_EXIT="3")
        result = subprocess.run(
            [
                "/bin/bash", str(SHIMS["codex"]), str(prompt),
                "--routing-workspace=isolated", "--routing-task-mode=write",
            ],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(3, result.returncode)
        run = sandbox.run_directories()[0]
        terminal = json.loads((run / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("failed", terminal["status"])
        self.assertIn(b"partial.txt", (run / "changes.patch").read_bytes())
        self.assertTrue((Path(terminal["workspace"]["path"]) / "partial.txt").is_file())

    def test_terminal_state_cannot_transition_back_to_running(self) -> None:
        sandbox = self.sandbox()
        store = RunStore.create(sandbox.environment(), "00000000-0000-4000-8000-000000000001")
        emitter = EventEmitter(store, provider="codex", model="gpt-test")
        lifecycle = Lifecycle(store, "codex", "gpt-test", emitter)
        for state in ("preflighting", "ready", "running", "succeeded"):
            lifecycle.transition(state)
        with self.assertRaisesRegex(RuntimeError, "invalid dispatch transition|terminal"):
            lifecycle.transition("running")

    def test_hook_output_is_captured_before_an_unchanged_final_sentinel(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        config = sandbox.config / "subagent-model-routing/hooks.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "dispatch.succeeded": [
                        {
                            "command": [sys.executable, "-c", "import sys; print('hook-stdout'); print('hook-stderr', file=sys.stderr)"],
                            "timeoutSeconds": 2,
                            "failurePolicy": "ignore",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = sandbox.run("codex", [str(prompt)])
        self.assertEqual(0, result.returncode)
        self.assertEqual(b"fake-provider\n\nSHIM-DONE exit=0\n", result.stdout)
        self.assertNotIn(b"hook", result.stderr)
        hook_logs = list((sandbox.run_directories()[0] / "hooks").glob("*.stdout.log"))
        self.assertEqual(1, len(hook_logs))
        self.assertEqual(b"hook-stdout\n", hook_logs[0].read_bytes())

    def test_workflow_lineage_is_persisted_in_results_events_and_run_state(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt("workflow task\n")
        env = sandbox.environment()
        dispatch_id = "10000000-0000-4000-8000-000000000001"
        env.update({
            "SUBAGENT_MODEL_ROUTING_DISPATCH_ID": dispatch_id,
            "SUBAGENT_MODEL_ROUTING_WORKFLOW_ID": "20000000-0000-4000-8000-000000000002",
            "SUBAGENT_MODEL_ROUTING_TASK_ID": "review",
            "SUBAGENT_MODEL_ROUTING_ATTEMPT": "2",
            "SUBAGENT_MODEL_ROUTING_EFFORT": "high",
        })
        result = sandbox.run("codex", [str(prompt)], env=env)
        self.assertEqual(0, result.returncode)
        run = sandbox.run_directories()[0]
        self.assertEqual(dispatch_id, run.name)
        document = json.loads((run / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(env["SUBAGENT_MODEL_ROUTING_WORKFLOW_ID"], document["workflowId"])
        self.assertEqual("review", document["taskId"])
        self.assertEqual("high", document["effort"])
        run_state = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(2, run_state["attempt"])
        events = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(event["workflowId"] == document["workflowId"] and event["taskId"] == "review" for event in events))

    def test_preassigned_dispatch_id_cannot_overwrite_an_existing_run(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt("first\n")
        env = sandbox.environment()
        env["SUBAGENT_MODEL_ROUTING_DISPATCH_ID"] = "30000000-0000-4000-8000-000000000003"
        self.assertEqual(0, sandbox.run("codex", [str(prompt)], env=env).returncode)
        second = sandbox.run("codex", [str(prompt)], env=env)
        self.assertEqual(64, second.returncode)
        self.assertIn(b"dispatch ID already exists", second.stderr)

    def test_ctrl_c_cancels_provider_process_group_and_records_cancelled_result(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        child_pid_file = sandbox.root / "child.pid"
        env = sandbox.environment(
            FAKE_SLEEP_SECS="30",
            FAKE_SPAWN_CHILD_SECS="30",
            FAKE_CHILD_PID_FILE=str(child_pid_file),
        )
        process = subprocess.Popen(
            ["/bin/bash", str(SHIMS["codex"]), str(prompt)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not child_pid_file.exists():
                time.sleep(0.02)
            self.assertTrue(child_pid_file.exists(), "fake provider did not spawn its child")
            child_pid = int(child_pid_file.read_text(encoding="ascii"))
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(130, process.returncode, stderr.decode(errors="replace"))
            self.assertTrue(stdout.endswith(b"\nSHIM-DONE exit=130\n"))
            result = json.loads((sandbox.run_directories()[0] / "result.json").read_text(encoding="utf-8"))
            self.assertEqual("cancelled", result["status"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                stat = Path(f"/proc/{child_pid}/stat")
                if not stat.exists() or stat.read_text(encoding="utf-8").split()[2] == "Z":
                    break
                time.sleep(0.02)
            else:
                self.fail("provider grandchild survived Ctrl+C cancellation")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_normal_provider_exit_reaps_background_grandchild_before_sentinel(self) -> None:
        sandbox = self.sandbox()
        sandbox.install_provider("codex")
        prompt = sandbox.prompt()
        child_pid_file = sandbox.root / "background-child.pid"
        result = sandbox.run(
            "codex",
            [str(prompt)],
            env=sandbox.environment(
                FAKE_SPAWN_CHILD_SECS="30",
                FAKE_CHILD_PID_FILE=str(child_pid_file),
            ),
            timeout=8,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual(b"fake-provider\n\nSHIM-DONE exit=0\n", result.stdout)
        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            stat = Path(f"/proc/{child_pid}/stat")
            if not stat.exists() or stat.read_text(encoding="utf-8").split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            self.fail("background provider grandchild survived normal parent exit")


if __name__ == "__main__":
    unittest.main()
