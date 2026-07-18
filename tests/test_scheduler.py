"""Acceptance tests for persistent Phase 6 workflow scheduling."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.run_store import atomic_write_json, ensure_private_directory, state_root  # noqa: E402
from model_routing.scheduler import (  # noqa: E402
    AttemptOutcome,
    _StateController,
    _provider_args,
    WorkflowRunError,
    cancel_workflow,
    list_workflows,
    resume_workflow,
    run_workflow,
    show_workflow,
)
from tests.test_workflow import make_registry  # noqa: E402


class ProviderArgumentTests(unittest.TestCase):
    def test_kimi_workflow_uses_prompt_file_and_model_override(self) -> None:
        prompt = Path("/tmp/kimi-prompt.md")
        self.assertEqual(
            [str(prompt), "--model", "kimi-code/kimi-for-coding"],
            _provider_args(
                "kimi",
                {"provider": "kimi", "model": "kimi-code/kimi-for-coding"},
                prompt,
            ),
        )


def task(*, depends: list[str] | None = None, context: list[dict] | None = None, verify: list[list[str]] | None = None, retry: dict | None = None, mode: str = "read") -> dict:
    value = {
        "route": {"provider": "opencode", "model": "test/model-1"},
        "mode": mode,
        "prompt": {"text": "do the task"},
        "dependsOn": depends or [],
    }
    if context is not None:
        value["contextFrom"] = context
    if verify is not None:
        value["verify"] = verify
    if retry is not None:
        value["retry"] = retry
    return value


class FakeRunner:
    def __init__(self, env: dict[str, str], repo: Path, behaviors: dict[str, list[tuple[str, int, bool]]] | None = None, delay: float = 0.0) -> None:
        self.env = env
        self.repo = repo
        self.behaviors = behaviors or {}
        self.delay = delay
        self.lock = threading.Lock()
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0

    def __call__(self, task_id, task_value, prompt, attempt, dispatch_id, workflow_id, workflow_dir, env, repo_root):
        started = time.monotonic()
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        if self.delay:
            time.sleep(self.delay)
        sequence = self.behaviors.get(task_id, [("succeeded", 0, False)])
        index = sum(1 for call in self.calls if call["task"] == task_id)
        status, exit_code, transport = sequence[min(index, len(sequence) - 1)]
        run_dir = state_root(env) / "runs" / dispatch_id
        ensure_private_directory(run_dir)
        (run_dir / "stdout.log").write_bytes((f"output-{task_id}-" + "x" * 100).encode())
        (run_dir / "stderr.log").write_bytes(b"")
        (run_dir / "changes.patch").write_bytes(b"patch")
        atomic_write_json(run_dir / "changeset.json", {"diffstat": {"files": 1}})
        workspace = repo_root
        if task_value["mode"] == "write":
            workspace = workflow_dir / "fake-worktrees" / dispatch_id
            ensure_private_directory(workspace)
        result_path = run_dir / "result.json"
        atomic_write_json(result_path, {
            "dispatchId": dispatch_id,
            "workflowId": workflow_id,
            "taskId": task_id,
            "status": status,
            "workspace": {"path": str(workspace), "mode": "isolated" if task_value["mode"] == "write" else "shared"},
        })
        finished = time.monotonic()
        with self.lock:
            self.active -= 1
            self.calls.append({
                "task": task_id,
                "attempt": attempt,
                "dispatch": dispatch_id,
                "prompt": bytes(prompt),
                "started": started,
                "finished": finished,
            })
        return AttemptOutcome(
            dispatch_id,
            status,
            exit_code,
            result_path=str(result_path),
            workspace_path=str(workspace),
            transport_error=transport,
        )


class SchedulerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "seed"], check=True)
        self.env = {
            "HOME": str(self.root / "home"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "PATH": os.environ.get("PATH", ""),
        }
        self.registry = make_registry()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def workflow(self, tasks: dict, defaults: dict | None = None) -> Path:
        value = {"schemaVersion": 1, "name": "test-workflow", "tasks": tasks}
        if defaults is not None:
            value["defaults"] = defaults
        path = self.repo / f"workflow-{time.monotonic_ns()}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def execute(self, path: Path, runner: FakeRunner):
        return run_workflow(path, host="copilot", repo_root=self.repo, env=self.env, registry=self.registry, runner=runner)


class SchedulingTests(SchedulerFixture):
    def test_independent_roots_overlap_and_dependent_waits(self) -> None:
        runner = FakeRunner(self.env, self.repo, delay=0.08)
        state = self.execute(self.workflow({"a": task(), "b": task(), "c": task(depends=["a", "b"])}), runner)
        self.assertEqual("succeeded", state["status"], state)
        self.assertGreaterEqual(runner.max_active, 2)
        by_task = {call["task"]: call for call in runner.calls}
        self.assertGreaterEqual(by_task["c"]["started"], max(by_task["a"]["finished"], by_task["b"]["finished"]))

    def test_provider_concurrency_serializes_same_provider(self) -> None:
        runner = FakeRunner(self.env, self.repo, delay=0.04)
        path = self.workflow(
            {"a": task(), "b": task()},
            {"maxConcurrency": 2, "providerConcurrency": {"opencode": 1}},
        )
        self.execute(path, runner)
        self.assertEqual(1, runner.max_active)

    def test_fail_fast_skips_unstarted_branch_and_continue_runs_it(self) -> None:
        tasks = {"bad": task(), "after": task(depends=["bad"]), "other": task(depends=["gate"]), "gate": task()}
        fail_runner = FakeRunner(self.env, self.repo, {"bad": [("failed", 1, False)]}, delay=0.03)
        failed = self.execute(self.workflow(tasks, {"maxConcurrency": 1, "failurePolicy": "fail-fast"}), fail_runner)
        self.assertEqual("blocked", failed["tasks"]["after"]["state"])
        self.assertEqual("skipped", failed["tasks"]["gate"]["state"])
        self.assertEqual("blocked", failed["tasks"]["other"]["state"])
        continue_runner = FakeRunner(self.env, self.repo, {"bad": [("failed", 1, False)]})
        continued = self.execute(self.workflow(tasks, {"maxConcurrency": 2, "failurePolicy": "continue"}), continue_runner)
        self.assertEqual("succeeded", continued["tasks"]["other"]["state"])
        self.assertEqual(1, sum(call["task"] == "other" for call in continue_runner.calls))

    def test_no_task_runs_twice(self) -> None:
        runner = FakeRunner(self.env, self.repo, delay=0.02)
        self.execute(self.workflow({"a": task(), "b": task(depends=["a"])}), runner)
        self.assertEqual({"a": 1, "b": 1}, {name: sum(call["task"] == name for call in runner.calls) for name in ("a", "b")})


class ContextRetryVerificationTests(SchedulerFixture):
    def test_only_explicit_context_is_added_and_truncated(self) -> None:
        runner = FakeRunner(self.env, self.repo)
        path = self.workflow({
            "source": task(),
            "plain": task(depends=["source"]),
            "selected": task(depends=["source"], context=[{"task": "source", "artifact": "stdout", "maxBytes": 12}]),
        })
        self.execute(path, runner)
        prompts = {call["task"]: call["prompt"] for call in runner.calls}
        self.assertNotIn(b"dependency context", prompts["plain"])
        self.assertIn(b"dependency context", prompts["selected"])
        self.assertIn(b"truncated: true", prompts["selected"])
        self.assertNotIn(b"x" * 20, prompts["selected"])

    def test_retry_policy_uses_fresh_dispatch_ids_and_usage_errors_never_retry(self) -> None:
        runner = FakeRunner(self.env, self.repo, {
            "flaky": [("timed_out", 124, False), ("succeeded", 0, False)],
            "usage": [("failed", 64, True)],
        })
        retry = {"maxAttempts": 2, "backoffSeconds": 0, "on": ["timeout", "transport-error"]}
        state = self.execute(self.workflow({"flaky": task(retry=retry), "usage": task(retry=retry)}, {"failurePolicy": "continue"}), runner)
        flaky = [call for call in runner.calls if call["task"] == "flaky"]
        self.assertEqual(2, len(flaky))
        self.assertEqual(2, len({call["dispatch"] for call in flaky}))
        self.assertEqual(1, sum(call["task"] == "usage" for call in runner.calls))
        self.assertEqual("succeeded", state["tasks"]["flaky"]["state"])

    def test_verification_records_argv_and_distinguishes_failure(self) -> None:
        runner = FakeRunner(self.env, self.repo)
        state = self.execute(self.workflow({
            "good": task(verify=[[sys.executable, "-c", "print('ok')"]]),
            "bad": task(verify=[[sys.executable, "-c", "raise SystemExit(3)"]]),
            "large": task(
                verify=[[
                    sys.executable,
                    "-c",
                    "import os; os.write(1, b'x' * (2 * 1024 * 1024))",
                ]]
            ),
        }, {"failurePolicy": "continue"}), runner)
        self.assertEqual("verified", state["tasks"]["good"]["state"])
        self.assertEqual("verification_failed", state["tasks"]["bad"]["state"])
        record = json.loads(Path(state["tasks"]["good"]["verificationPath"]).read_text(encoding="utf-8"))
        self.assertEqual([sys.executable, "-c", "print('ok')"], record["commands"][0]["argv"])
        large = json.loads(
            Path(state["tasks"]["large"]["verificationPath"]).read_text(encoding="utf-8")
        )["commands"][0]
        self.assertEqual(1024 * 1024, len(large["stdout"]))
        self.assertEqual(2 * 1024 * 1024, large["stdoutBytes"])
        self.assertTrue(large["stdoutTruncated"])


class ResumeAndStorageTests(SchedulerFixture):
    def test_resume_skips_completed_task_and_retries_incomplete_task(self) -> None:
        first_runner = FakeRunner(self.env, self.repo, {"b": [("failed", 1, False)]})
        first = self.execute(self.workflow({"a": task(), "b": task()}, {"failurePolicy": "continue"}), first_runner)
        second_runner = FakeRunner(self.env, self.repo)
        resumed = resume_workflow(first["workflowId"], repo_root=self.repo, env=self.env, registry=self.registry, runner=second_runner)
        self.assertEqual("succeeded", resumed["status"])
        self.assertEqual(0, sum(call["task"] == "a" for call in second_runner.calls))
        self.assertEqual(1, sum(call["task"] == "b" for call in second_runner.calls))
        self.assertEqual(2, len(resumed["tasks"]["b"]["attempts"]))

    def test_resume_rejects_a_declared_host_that_differs_from_the_stored_host(self) -> None:
        runner = FakeRunner(self.env, self.repo)
        state = self.execute(self.workflow({"a": task()}), runner)
        with self.assertRaisesRegex(WorkflowRunError, "host mismatch"):
            resume_workflow(
                state["workflowId"],
                repo_root=self.repo,
                env=self.env,
                registry=self.registry,
                runner=runner,
                declared_host="claude",
            )

    def test_resume_rejects_digest_registry_repo_and_missing_worktree(self) -> None:
        runner = FakeRunner(self.env, self.repo)
        state = self.execute(self.workflow({"write": task(mode="write")}), runner)
        workflow_dir = state_root(self.env) / "workflows" / state["workflowId"]
        workflow_doc = json.loads((workflow_dir / "workflow.json").read_text(encoding="utf-8"))
        workflow_doc["name"] = "tampered"
        atomic_write_json(workflow_dir / "workflow.json", workflow_doc)
        with self.assertRaisesRegex(WorkflowRunError, "digest"):
            resume_workflow(state["workflowId"], repo_root=self.repo, env=self.env, registry=self.registry, runner=runner)
        atomic_write_json(workflow_dir / "workflow.json", {**workflow_doc, "name": "test-workflow"})
        changed_registry = json.loads(json.dumps(self.registry))
        changed_registry["schemaVersion"] = 99
        with self.assertRaisesRegex(WorkflowRunError, "registry"):
            resume_workflow(state["workflowId"], repo_root=self.repo, env=self.env, registry=changed_registry, runner=runner)
        other = self.root / "other"
        other.mkdir()
        with self.assertRaisesRegex(WorkflowRunError, "repository"):
            resume_workflow(state["workflowId"], repo_root=other, env=self.env, registry=self.registry, runner=runner)
        workspace = Path(state["tasks"]["write"]["attempts"][-1]["workspacePath"])
        workspace.rmdir()
        with self.assertRaisesRegex(WorkflowRunError, "worktree"):
            resume_workflow(state["workflowId"], repo_root=self.repo, env=self.env, registry=self.registry, runner=runner)

    def test_list_show_cancel_and_private_state(self) -> None:
        runner = FakeRunner(self.env, self.repo)
        state = self.execute(self.workflow({"a": task()}), runner)
        listed = list_workflows(self.env)
        self.assertEqual(state["workflowId"], listed[0]["workflowId"])
        self.assertEqual(state["status"], show_workflow(self.env, state["workflowId"])["status"])
        cancelled = cancel_workflow(self.env, state["workflowId"])
        self.assertFalse(cancelled["cancellationRequested"])
        self.assertEqual("succeeded", cancelled["status"])
        self.assertFalse(cancel_workflow(self.env, state["workflowId"])["cancellationRequested"])
        directory = state_root(self.env) / "workflows" / state["workflowId"]
        self.assertEqual(0o700, directory.stat().st_mode & 0o777)
        self.assertEqual(0o600, (directory / "state.json").stat().st_mode & 0o777)

    def test_cancel_never_signals_a_stale_or_reused_pid_without_runner_lease(self) -> None:
        runner = FakeRunner(self.env, self.repo)
        state = self.execute(self.workflow({"a": task()}), runner)
        directory = state_root(self.env) / "workflows" / state["workflowId"]
        stale = json.loads((directory / "state.json").read_text(encoding="utf-8"))
        stale.update({"status": "running", "runnerPid": 424242})
        atomic_write_json(directory / "state.json", stale)
        with mock.patch("model_routing.scheduler.os.kill") as kill:
            cancelled = cancel_workflow(self.env, state["workflowId"])
        kill.assert_not_called()
        self.assertTrue(cancelled["cancellationRequested"])

    def test_controller_preserves_external_cancellation_request_on_next_write(self) -> None:
        runner = FakeRunner(self.env, self.repo)
        state = self.execute(self.workflow({"a": task()}), runner)
        directory = state_root(self.env) / "workflows" / state["workflowId"]
        persisted = json.loads((directory / "state.json").read_text(encoding="utf-8"))
        persisted.update({"status": "running", "runnerPid": None})
        atomic_write_json(directory / "state.json", persisted)
        stale_controller_state = json.loads(json.dumps(persisted))
        cancel_workflow(self.env, state["workflowId"])
        self.assertFalse(stale_controller_state["cancellationRequested"])
        controller = _StateController(directory, stale_controller_state)
        controller.write()
        merged = json.loads((directory / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(merged["cancellationRequested"])


class ProductionRunnerTests(SchedulerFixture):
    def production_env(self, **updates: str) -> dict[str, str]:
        fake_binary = self.root / "fake-opencode"
        fake_binary.write_bytes((ROOT / "tests" / "fixtures" / "fake_provider.py").read_bytes())
        fake_binary.chmod(0o755)
        env = dict(self.env)
        env.update({
            "OPENCODE_BIN": str(fake_binary),
            "SUBAGENT_MODEL_ROUTING_UNRESTRICTED": "0",
            "PYTHONPATH": str(ROOT / "runtime"),
        })
        env.update(updates)
        return env

    def test_production_runner_assigns_lineage_before_dispatch(self) -> None:
        env = self.production_env()
        state = run_workflow(
            self.workflow({"agent": task()}),
            host="copilot",
            repo_root=self.repo,
            env=env,
            registry=self.registry,
        )
        self.assertEqual("succeeded", state["status"], state)
        attempt = state["tasks"]["agent"]["attempts"][0]
        result = json.loads(Path(attempt["resultPath"]).read_text(encoding="utf-8"))
        self.assertEqual(state["workflowId"], result["workflowId"])
        self.assertEqual("agent", result["taskId"])
        self.assertEqual(attempt["dispatchId"], result["dispatchId"])

    def test_cli_cancel_interrupts_active_dispatch_and_leaves_resumable_state(self) -> None:
        env = self.production_env(FAKE_SLEEP_SECS="30")
        workflow = self.workflow({"slow": task()})
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "model-routing"), "workflow", "run", str(workflow), "--host", "copilot"],
            cwd=self.repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            workflows_root = state_root(env) / "workflows"
            deadline = time.monotonic() + 8
            workflow_dir = None
            while time.monotonic() < deadline:
                candidates = list(workflows_root.glob("*/state.json")) if workflows_root.is_dir() else []
                if candidates:
                    candidate_state = json.loads(candidates[0].read_text(encoding="utf-8"))
                    if candidate_state["tasks"]["slow"]["state"] == "running":
                        workflow_dir = candidates[0].parent
                        break
                time.sleep(0.02)
            self.assertIsNotNone(workflow_dir, "workflow task never reached running state")
            cancelled = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "model-routing"), "workflow", "cancel", workflow_dir.name],
                cwd=self.repo,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=8,
                check=False,
            )
            self.assertEqual(0, cancelled.returncode, cancelled.stderr.decode(errors="replace"))
            stdout, stderr = process.communicate(timeout=12)
            self.assertEqual(1, process.returncode, stderr.decode(errors="replace"))
            final = json.loads((workflow_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("cancelled", final["status"])
            self.assertEqual("cancelled", final["tasks"]["slow"]["state"])
            self.assertIn(workflow_dir.name, final["resumeCommand"])
            self.assertIn("--host copilot", final["resumeCommand"])
            self.assertIn(b'"status": "cancelled"', stdout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
