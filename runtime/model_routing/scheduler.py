"""Persistent host-neutral dependency workflow scheduler."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, Protocol
import uuid

from .run_store import (
    FILE_MODE,
    atomic_write_bytes,
    atomic_write_json,
    ensure_private_directory,
    state_root,
    utc_now,
)
from .process import run_bounded_capture
from .workflow import load_workflow, validate_workflow, workflow_digest


TERMINAL_SUCCESS = {"succeeded", "verified"}
TERMINAL_FAILURE = {"failed", "timed_out", "cancelled", "verification_failed", "blocked", "skipped"}
TERMINAL_STATES = TERMINAL_SUCCESS | TERMINAL_FAILURE
TERMINAL_WORKFLOW_STATES = {"succeeded", "failed", "cancelled"}
MAX_CONTEXT_BYTES = 1024 * 1024


class WorkflowRunError(RuntimeError):
    """Raised when a persisted workflow cannot safely run or resume."""


@dataclass(slots=True)
class AttemptOutcome:
    dispatch_id: str
    status: str
    exit_code: int
    result_path: str | None = None
    workspace_path: str | None = None
    transport_error: bool = False
    stdout_path: str | None = None
    stderr_path: str | None = None


class TaskRunner(Protocol):
    def __call__(
        self,
        task_id: str,
        task: Mapping[str, Any],
        prompt: bytes,
        attempt: int,
        dispatch_id: str,
        workflow_id: str,
        workflow_dir: Path,
        env: Mapping[str, str],
        repo_root: Path,
    ) -> AttemptOutcome: ...


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _workflow_root(env: Mapping[str, str]) -> Path:
    return state_root(env) / "workflows"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowRunError(f"cannot read workflow state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowRunError(f"workflow state {path} is not an object")
    return value


def _find_workflow_dir(env: Mapping[str, str], workflow_id: str) -> Path:
    root = _workflow_root(env)
    if not root.is_dir():
        raise WorkflowRunError(f"workflow {workflow_id!r} not found")
    matches = [path for path in root.iterdir() if path.is_dir() and (path.name == workflow_id or path.name.startswith(workflow_id))]
    if len(matches) != 1:
        raise WorkflowRunError(f"workflow {workflow_id!r} {'not found' if not matches else 'ambiguous'}")
    return matches[0]


def _git_common_dir(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    path = Path(result.stdout.decode("utf-8", errors="replace").strip())
    if not path.is_absolute():
        path = repo_root / path
    return str(path.resolve())


def _pid_alive(pid: Any) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class _WorkflowFileLock:
    def __init__(self, directory: Path, name: str, *, nonblocking: bool = False) -> None:
        self.path = directory / name
        self.nonblocking = nonblocking
        self.descriptor: int | None = None

    def acquire(self) -> bool:
        ensure_private_directory(self.path.parent)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT, FILE_MODE)
        flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if self.nonblocking else 0)
        try:
            fcntl.flock(descriptor, flags)
        except BlockingIOError:
            os.close(descriptor)
            return False
        self.descriptor = descriptor
        return True

    def release(self) -> None:
        if self.descriptor is None:
            return
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.descriptor = None

    def __enter__(self) -> "_WorkflowFileLock":
        if not self.acquire():
            raise WorkflowRunError(f"workflow lock is already held: {self.path}")
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.release()


def _runner_active(directory: Path) -> bool:
    probe = _WorkflowFileLock(directory, "runner.lock", nonblocking=True)
    if not probe.acquire():
        return True
    probe.release()
    return False


class _StateController:
    def __init__(self, directory: Path, state: dict[str, Any]) -> None:
        self.directory = directory
        self.state = state
        self.lock = threading.RLock()

    def write(self) -> None:
        with self.lock:
            with _WorkflowFileLock(self.directory, "state.lock"):
                state_path = self.directory / "state.json"
                if state_path.is_file():
                    persisted = _load_json(state_path)
                    if persisted.get("cancellationRequested"):
                        self.state["cancellationRequested"] = True
                self.state["updatedAt"] = utc_now()
                atomic_write_json(state_path, self.state)

    def mutate(self, callback: Callable[[dict[str, Any]], None]) -> None:
        with self.lock:
            callback(self.state)
            self.write()


class _ProductionRunner:
    def __init__(self, registry: Mapping[str, Any]) -> None:
        self.registry = registry
        self._lock = threading.Lock()
        self._active: dict[str, subprocess.Popen[bytes]] = {}

    def cancel_active(self) -> None:
        with self._lock:
            processes = list(self._active.values())
        for process in processes:
            if process.poll() is None:
                try:
                    process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass

    def __call__(
        self,
        task_id: str,
        task: Mapping[str, Any],
        prompt: bytes,
        attempt: int,
        dispatch_id: str,
        workflow_id: str,
        workflow_dir: Path,
        env: Mapping[str, str],
        repo_root: Path,
    ) -> AttemptOutcome:
        attempt_dir = workflow_dir / "tasks" / task_id / f"attempt-{attempt}"
        ensure_private_directory(attempt_dir)
        prompt_path = attempt_dir / "prompt.md"
        stdout_path = attempt_dir / "wrapper.stdout.log"
        stderr_path = attempt_dir / "wrapper.stderr.log"
        atomic_write_bytes(prompt_path, prompt)
        route = task["route"]
        provider = route["provider"]
        args = _provider_args(provider, route, prompt_path)
        args.extend(["--routing-workspace", task["workspace"], "--routing-task-mode", task["mode"]])
        command = [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "model-routing"), "_shim", provider, *args]
        child_env = dict(env)
        child_env.update({
            "SUBAGENT_MODEL_ROUTING_DISPATCH_ID": dispatch_id,
            "SUBAGENT_MODEL_ROUTING_WORKFLOW_ID": workflow_id,
            "SUBAGENT_MODEL_ROUTING_TASK_ID": task_id,
            "SUBAGENT_MODEL_ROUTING_ATTEMPT": str(attempt),
            "SHIM_TIMEOUT_SECS": str(task["timeoutSeconds"]),
        })
        if route.get("effort") is not None:
            child_env["SUBAGENT_MODEL_ROUTING_EFFORT"] = str(route["effort"])
        stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        try:
            process = subprocess.Popen(command, cwd=repo_root, env=child_env, stdout=stdout_fd, stderr=stderr_fd)
        except OSError:
            os.close(stdout_fd)
            os.close(stderr_fd)
            return AttemptOutcome(dispatch_id, "failed", 127, transport_error=True, stdout_path=str(stdout_path), stderr_path=str(stderr_path))
        os.close(stdout_fd)
        os.close(stderr_fd)
        with self._lock:
            self._active[dispatch_id] = process
        try:
            exit_code = process.wait()
        finally:
            with self._lock:
                self._active.pop(dispatch_id, None)
        result_path = state_root(env) / "runs" / dispatch_id / "result.json"
        result: dict[str, Any] | None = None
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        status = str(result.get("status")) if isinstance(result, dict) else (
            "timed_out" if exit_code == 124 else "cancelled" if exit_code == 130 else "failed"
        )
        workspace_path = None
        if isinstance(result, dict) and isinstance(result.get("workspace"), dict):
            value = result["workspace"].get("path")
            workspace_path = value if isinstance(value, str) else None
        transport_error = result is None or status == "preflight_failed" or exit_code == 127
        return AttemptOutcome(
            dispatch_id=dispatch_id,
            status=status,
            exit_code=max(0, min(255, exit_code)),
            result_path=str(result_path) if result_path.is_file() else None,
            workspace_path=workspace_path,
            transport_error=transport_error,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )


def _provider_args(provider: str, route: Mapping[str, Any], prompt_path: Path) -> list[str]:
    model = str(route["model"])
    effort = route.get("effort")
    if provider == "codex":
        args = [str(prompt_path), "-m", model]
        if effort is not None:
            args.extend(["-c", f"model_reasoning_effort={effort}"])
        return args
    if provider == "claude":
        args = [str(prompt_path), "--model", model]
        if effort is not None:
            args.extend(["--effort", str(effort)])
        return args
    if provider == "grok":
        args = [str(prompt_path), "--model", model]
        if effort is not None:
            args.extend(["--effort", str(effort)])
        return args
    if provider == "kimi":
        return [str(prompt_path), "--model", model]
    if provider == "opencode":
        args = [model, str(prompt_path)]
        if effort is not None:
            args.extend(["--variant", str(effort)])
        return args
    raise WorkflowRunError(f"unsupported workflow provider: {provider}")


def _snapshot_prompts(normalized: Mapping[str, Any], source_path: Path, directory: Path) -> dict[str, str]:
    prompt_dir = directory / "prompts"
    ensure_private_directory(prompt_dir)
    snapshots: dict[str, str] = {}
    for task_id, task in normalized["tasks"].items():
        prompt = task["prompt"]
        if "text" in prompt:
            content = prompt["text"].encode("utf-8")
        else:
            content = (source_path.parent / prompt["file"]).resolve().read_bytes()
        relative = f"prompts/{task_id}.md"
        atomic_write_bytes(directory / relative, content)
        snapshots[task_id] = relative
    return snapshots


def _contained_file(root: Path, relative: str, label: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise WorkflowRunError(f"{label} escapes its workflow directory") from exc
    if not candidate.is_file():
        raise WorkflowRunError(f"{label} is missing: {candidate}")
    return candidate


def _artifact_payload(
    env: Mapping[str, str],
    dep: Mapping[str, Any],
    artifact: str,
    maximum: int,
) -> tuple[bytes, int]:
    attempts = dep.get("attempts", [])
    if not attempts:
        raise WorkflowRunError("dependency has no attempt artifacts")
    dispatch_id = attempts[-1]["dispatchId"]
    try:
        uuid.UUID(dispatch_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise WorkflowRunError("dependency attempt has an invalid dispatch ID") from exc
    run_dir = state_root(env) / "runs" / dispatch_id
    names = {
        "stdout": "stdout.log",
        "stderr": "stderr.log",
        "result": "result.json",
        "patch": "changes.patch",
        "diffstat": "changeset.json",
    }
    path = run_dir / names[artifact]
    try:
        original_size = path.stat().st_size
        with path.open("rb") as handle:
            content = handle.read(maximum)
    except OSError as exc:
        raise WorkflowRunError(f"cannot read dependency artifact {path}: {exc}") from exc
    if artifact == "diffstat":
        try:
            value = json.loads(content)
            content = json.dumps(value.get("diffstat", value), sort_keys=True, indent=2).encode("utf-8")[:maximum]
        except (json.JSONDecodeError, AttributeError):
            pass
    return content, original_size


def _compose_prompt(
    directory: Path,
    state: Mapping[str, Any],
    normalized: Mapping[str, Any],
    task_id: str,
    env: Mapping[str, str],
) -> bytes:
    snapshot = state["promptSnapshots"].get(task_id)
    if not isinstance(snapshot, str):
        raise WorkflowRunError(f"task {task_id} is missing its prompt snapshot")
    original = _contained_file(directory, snapshot, f"task {task_id} prompt snapshot").read_bytes()
    sections = [original]
    task = normalized["tasks"][task_id]
    for selection in task["contextFrom"]:
        dep_id = selection["task"]
        artifact = selection["artifact"]
        maximum = min(selection["maxBytes"], MAX_CONTEXT_BYTES)
        selected, original_size = _artifact_payload(env, state["tasks"][dep_id], artifact, maximum)
        truncated = original_size > maximum
        dep_route = normalized["tasks"][dep_id]["route"]
        header = (
            f"\n\n--- dependency context ---\n"
            f"task: {dep_id}\nprovider: {dep_route['provider']}\nmodel: {dep_route['model']}\n"
            f"status: {state['tasks'][dep_id]['state']}\nartifact: {artifact}\n"
            f"bytes: {original_size}\ntruncated: {'true' if truncated else 'false'}\n---\n"
        ).encode("utf-8")
        sections.extend([header, selected, b"\n--- end dependency context ---\n"])
    return b"".join(sections)


def _run_verification(
    task_id: str,
    task: Mapping[str, Any],
    outcome: AttemptOutcome,
    directory: Path,
    env: Mapping[str, str],
) -> tuple[str, str | None]:
    commands = task["verify"]
    if not commands:
        return "succeeded", None
    workspace = Path(outcome.workspace_path or ".")
    records: list[dict[str, Any]] = []
    status = "verified"
    for argv in commands:
        started = time.monotonic()
        try:
            result = run_bounded_capture(
                list(argv),
                cwd=workspace,
                env=env,
                timeout_seconds=float(task["timeoutSeconds"]),
                max_bytes=MAX_CONTEXT_BYTES,
            )
            exit_code = 124 if result.timed_out else result.returncode
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            stdout_bytes = result.stdout_bytes
            stderr_bytes = result.stderr_bytes
            stdout_truncated = result.stdout_truncated
            stderr_truncated = result.stderr_truncated
        except OSError as exc:
            exit_code, stdout, stderr = 127, "", str(exc)
            stdout_bytes, stderr_bytes = 0, len(stderr.encode("utf-8"))
            stdout_truncated = stderr_truncated = False
        records.append({
            "argv": list(argv),
            "exitCode": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "stdoutBytes": stdout_bytes,
            "stderrBytes": stderr_bytes,
            "stdoutTruncated": stdout_truncated,
            "stderrTruncated": stderr_truncated,
            "wallMs": max(0, int((time.monotonic() - started) * 1000)),
        })
        if exit_code != 0:
            status = "verification_failed"
            break
    path = directory / "tasks" / task_id / "verification.json"
    atomic_write_json(path, {"schemaVersion": 1, "status": status, "commands": records})
    return status, str(path)


def _should_retry(task: Mapping[str, Any], outcome: AttemptOutcome, attempt_in_run: int) -> bool:
    retry = task["retry"]
    if attempt_in_run >= retry["maxAttempts"] or outcome.exit_code in {64, 66}:
        return False
    reasons = set(retry["on"])
    return (outcome.status == "timed_out" and "timeout" in reasons) or (outcome.transport_error and "transport-error" in reasons)


def _execute_task(
    task_id: str,
    normalized: Mapping[str, Any],
    controller: _StateController,
    env: Mapping[str, str],
    repo_root: Path,
    runner: TaskRunner,
    cancel_event: threading.Event,
) -> tuple[str, str | None]:
    task = normalized["tasks"][task_id]
    prompt = _compose_prompt(controller.directory, controller.state, normalized, task_id, env)
    with controller.lock:
        first_attempt = len(controller.state["tasks"][task_id]["attempts"]) + 1
    attempt_in_run = 0
    while True:
        attempt_in_run += 1
        attempt = first_attempt + attempt_in_run - 1
        dispatch_id = str(uuid.uuid4())
        started_at = utc_now()

        def started(state: dict[str, Any]) -> None:
            state["tasks"][task_id]["state"] = "running"
            state["tasks"][task_id]["attempts"].append({
                "attempt": attempt,
                "dispatchId": dispatch_id,
                "status": "running",
                "startedAt": started_at,
                "finishedAt": None,
            })
        controller.mutate(started)
        if cancel_event.is_set():
            outcome = AttemptOutcome(dispatch_id, "cancelled", 130)
        else:
            outcome = runner(
                task_id, task, prompt, attempt, dispatch_id, controller.state["workflowId"],
                controller.directory, env, repo_root,
            )

        def finished(state: dict[str, Any]) -> None:
            record = state["tasks"][task_id]["attempts"][-1]
            record.update({
                "status": outcome.status,
                "exitCode": outcome.exit_code,
                "resultPath": outcome.result_path,
                "workspacePath": outcome.workspace_path,
                "transportError": outcome.transport_error,
                "stdoutPath": outcome.stdout_path,
                "stderrPath": outcome.stderr_path,
                "finishedAt": utc_now(),
            })
        controller.mutate(finished)
        if cancel_event.is_set() or outcome.status == "cancelled":
            return "cancelled", None
        if outcome.status == "succeeded" and outcome.exit_code == 0:
            return _run_verification(
                task_id,
                task,
                outcome,
                controller.directory,
                env,
            )
        if not _should_retry(task, outcome, attempt_in_run):
            return ("timed_out" if outcome.status == "timed_out" else "failed"), None
        if cancel_event.wait(float(task["retry"]["backoffSeconds"])):
            return "cancelled", None


def _mark_dependency_states(state: dict[str, Any], normalized: Mapping[str, Any], fail_fast_triggered: bool) -> None:
    changed = True
    while changed:
        changed = False
        for task_id, task in normalized["tasks"].items():
            record = state["tasks"][task_id]
            if record["state"] not in {"pending", "ready"}:
                continue
            deps = [state["tasks"][dep]["state"] for dep in task["dependsOn"]]
            if any(dep in TERMINAL_FAILURE for dep in deps):
                record["state"] = "blocked"
                changed = True
            elif fail_fast_triggered:
                record["state"] = "skipped"
                changed = True
            elif all(dep in TERMINAL_SUCCESS for dep in deps):
                if record["state"] != "ready":
                    record["state"] = "ready"
                    changed = True


def _run_state_machine(
    normalized: Mapping[str, Any],
    controller: _StateController,
    env: Mapping[str, str],
    repo_root: Path,
    runner: TaskRunner,
) -> dict[str, Any]:
    runner_lease = _WorkflowFileLock(controller.directory, "runner.lock", nonblocking=True)
    if not runner_lease.acquire():
        raise WorkflowRunError("workflow already has an active scheduler")
    cancel_event = threading.Event()
    production = runner if isinstance(runner, _ProductionRunner) else None

    def request_cancel(_signum: int, _frame: Any) -> None:
        cancel_event.set()
        if production is not None:
            production.cancel_active()

    old_handlers: dict[int, Any] = {}
    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                old_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, request_cancel)

        def initialize(state: dict[str, Any]) -> None:
            state.update({"status": "running", "runnerPid": os.getpid(), "cancellationRequested": False})

        controller.mutate(initialize)
    except BaseException:
        for restore_signum, handler in old_handlers.items():
            signal.signal(restore_signum, handler)
        runner_lease.release()
        raise
    futures: dict[Future[tuple[str, str | None]], tuple[str, str]] = {}
    provider_active: dict[str, int] = {}
    failure_triggered = False
    maximum = normalized["defaults"]["maxConcurrency"]
    try:
        with ThreadPoolExecutor(max_workers=maximum, thread_name_prefix="model-routing-workflow") as executor:
            while True:
                if controller.state.get("cancellationRequested"):
                    request_cancel(signal.SIGINT, None)
                with controller.lock:
                    _mark_dependency_states(controller.state, normalized, failure_triggered)
                    running_ids = {task_id for task_id, _provider in futures.values()}
                    ready = [task_id for task_id, record in controller.state["tasks"].items() if record["state"] == "ready" and task_id not in running_ids]
                for task_id in ready:
                    if cancel_event.is_set() or len(futures) >= maximum:
                        break
                    provider = normalized["tasks"][task_id]["route"]["provider"]
                    provider_limit = normalized["defaults"]["providerConcurrency"].get(provider, maximum)
                    if provider_active.get(provider, 0) >= provider_limit:
                        continue
                    future = executor.submit(
                        _execute_task, task_id, normalized, controller, env, repo_root, runner, cancel_event
                    )
                    futures[future] = (task_id, provider)
                    provider_active[provider] = provider_active.get(provider, 0) + 1
                if not futures:
                    with controller.lock:
                        unfinished = [record for record in controller.state["tasks"].values() if record["state"] not in TERMINAL_STATES]
                    if not unfinished or cancel_event.is_set():
                        break
                    raise WorkflowRunError("workflow scheduler made no progress")
                completed, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in completed:
                    task_id, provider = futures.pop(future)
                    provider_active[provider] -= 1
                    try:
                        task_state, verification_path = future.result()
                    except Exception as exc:  # persisted as a task failure; scheduler continues deterministically
                        task_state, verification_path = "failed", None
                        def record_error(state: dict[str, Any], task_id: str = task_id, message: str = str(exc)) -> None:
                            state["tasks"][task_id]["error"] = message
                        controller.mutate(record_error)
                    def complete(state: dict[str, Any], task_id: str = task_id) -> None:
                        state["tasks"][task_id]["state"] = task_state
                        state["tasks"][task_id]["verificationPath"] = verification_path
                        state["tasks"][task_id]["finishedAt"] = utc_now()
                    controller.mutate(complete)
                    if task_state in {"failed", "timed_out", "cancelled", "verification_failed"}:
                        failure_triggered = normalized["defaults"]["failurePolicy"] == "fail-fast"
                if cancel_event.is_set() and production is not None:
                    production.cancel_active()
        with controller.lock:
            if cancel_event.is_set():
                for record in controller.state["tasks"].values():
                    if record["state"] in {"pending", "ready", "running"}:
                        record["state"] = "cancelled"
                overall = "cancelled"
            elif all(record["state"] in TERMINAL_SUCCESS for record in controller.state["tasks"].values()):
                overall = "succeeded"
            else:
                overall = "failed"
            controller.state.update({
                "status": overall,
                "runnerPid": None,
                "finishedAt": utc_now(),
                "resumeCommand": (
                    f"model-routing workflow resume {controller.state['workflowId']} "
                    f"--host {controller.state['host']}"
                ),
            })
            controller.write()
        return json.loads(json.dumps(controller.state))
    finally:
        for restore_signum, handler in old_handlers.items():
            signal.signal(restore_signum, handler)
        runner_lease.release()


def _initial_state(
    workflow_id: str,
    normalized: Mapping[str, Any],
    source_path: Path,
    repo_root: Path,
    registry: Mapping[str, Any],
    host: str,
    prompt_snapshots: Mapping[str, str],
    warnings: list[str],
) -> dict[str, Any]:
    created = utc_now()
    return {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "name": normalized["name"],
        "workflowDigest": workflow_digest(normalized),
        "registryDigest": _canonical_digest(registry),
        "host": host,
        "sourcePath": str(source_path.resolve()),
        "repoRoot": str(repo_root.resolve()),
        "gitCommonDir": _git_common_dir(repo_root),
        "status": "created",
        "createdAt": created,
        "updatedAt": created,
        "finishedAt": None,
        "runnerPid": None,
        "cancellationRequested": False,
        "warnings": list(warnings),
        "promptSnapshots": dict(prompt_snapshots),
        "tasks": {
            task_id: {"state": "pending", "attempts": [], "verificationPath": None, "finishedAt": None}
            for task_id in normalized["tasks"]
        },
    }


def run_workflow(
    path: Path,
    *,
    host: str,
    repo_root: Path,
    env: Mapping[str, str],
    registry: Mapping[str, Any],
    runner: TaskRunner | None = None,
) -> dict[str, Any]:
    source_path = Path(path).resolve()
    normalized = load_workflow(source_path, repo_root=repo_root, registry=registry, host=host)
    raw_source = json.loads(source_path.read_text(encoding="utf-8"))
    _validated, warnings = validate_workflow(
        raw_source,
        source_path=source_path,
        repo_root=repo_root,
        registry=registry,
        host=host,
    )
    workflow_id = str(uuid.uuid4())
    directory = _workflow_root(env) / workflow_id
    ensure_private_directory(directory)
    prompt_snapshots = _snapshot_prompts(normalized, source_path, directory)
    atomic_write_json(directory / "workflow.json", normalized)
    state = _initial_state(workflow_id, normalized, source_path, repo_root, registry, host, prompt_snapshots, warnings)
    controller = _StateController(directory, state)
    controller.write()
    selected_runner: TaskRunner = runner or _ProductionRunner(registry)
    return _run_state_machine(normalized, controller, env, Path(repo_root).resolve(), selected_runner)


def resume_workflow(
    workflow_id: str,
    *,
    repo_root: Path,
    env: Mapping[str, str],
    registry: Mapping[str, Any],
    runner: TaskRunner | None = None,
    declared_host: str | None = None,
) -> dict[str, Any]:
    directory = _find_workflow_dir(env, workflow_id)
    normalized = _load_json(directory / "workflow.json")
    state = _load_json(directory / "state.json")
    if declared_host is not None and state.get("host") != declared_host:
        raise WorkflowRunError(
            f"workflow host mismatch: stored {state.get('host')!r}, declared {declared_host!r}"
        )
    try:
        uuid.UUID(str(state.get("workflowId")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise WorkflowRunError("persisted workflow ID is invalid") from exc
    if state.get("workflowId") != directory.name:
        raise WorkflowRunError("persisted workflow ID does not match its state directory")
    if state.get("workflowDigest") != workflow_digest(normalized):
        raise WorkflowRunError("workflow digest mismatch; refusing resume")
    if state.get("registryDigest") != _canonical_digest(registry):
        raise WorkflowRunError("provider registry changed; refusing resume")
    if str(Path(repo_root).resolve()) != state.get("repoRoot") or _git_common_dir(Path(repo_root)) != state.get("gitCommonDir"):
        raise WorkflowRunError("workflow repository identity mismatch; refusing resume")
    if _runner_active(directory):
        raise WorkflowRunError("workflow is still running; refusing concurrent resume")
    if set(state.get("tasks", {})) != set(normalized.get("tasks", {})):
        raise WorkflowRunError("persisted workflow task set does not match the workflow digest")
    snapshots = state.get("promptSnapshots", {})
    if not isinstance(snapshots, dict) or set(snapshots) != set(normalized["tasks"]):
        raise WorkflowRunError("persisted prompt snapshot set does not match the workflow")
    for task_id, relative in snapshots.items():
        if task_id not in normalized["tasks"] or not isinstance(relative, str):
            raise WorkflowRunError("persisted prompt snapshot mapping is invalid")
        _contained_file(directory, relative, f"task {task_id} prompt snapshot")
    for task_id, record in state["tasks"].items():
        if not isinstance(record, dict):
            raise WorkflowRunError(f"task {task_id} has invalid persisted state")
        attempts = record.get("attempts")
        if not isinstance(attempts, list):
            raise WorkflowRunError(f"task {task_id} has invalid attempt history")
        for attempt in attempts:
            if not isinstance(attempt, dict):
                raise WorkflowRunError(f"task {task_id} has an invalid attempt record")
            try:
                uuid.UUID(str(attempt.get("dispatchId")))
            except (ValueError, TypeError, AttributeError) as exc:
                raise WorkflowRunError(f"task {task_id} has an invalid dispatch ID") from exc
        if record["state"] in TERMINAL_SUCCESS:
            if not attempts:
                raise WorkflowRunError(f"successful task {task_id} is missing its result artifact")
            latest = attempts[-1]
            expected_result = (state_root(env) / "runs" / latest["dispatchId"] / "result.json").resolve()
            result_path = latest.get("resultPath")
            if not isinstance(result_path, str) or Path(result_path).resolve() != expected_result or not expected_result.is_file():
                raise WorkflowRunError(f"successful task {task_id} has an unsafe or missing result artifact")
            result = _load_json(expected_result)
            if (
                result.get("workflowId") != state["workflowId"]
                or result.get("taskId") != task_id
                or result.get("dispatchId") != latest["dispatchId"]
                or result.get("status") != "succeeded"
            ):
                raise WorkflowRunError(f"successful task {task_id} result lineage/status mismatch")
            if normalized["tasks"][task_id]["mode"] == "write":
                workspace = latest.get("workspacePath")
                if normalized["tasks"][task_id]["workspace"] in {"auto", "isolated"} and (not workspace or not Path(workspace).is_dir()):
                    raise WorkflowRunError(f"successful write task {task_id} is missing its retained worktree")
        elif record["state"] == "running":
            record["state"] = "cancelled"
        elif record["state"] in TERMINAL_FAILURE | {"pending", "ready"}:
            record["state"] = "pending"
            record["finishedAt"] = None
    state.update({"status": "created", "runnerPid": None, "cancellationRequested": False, "finishedAt": None})
    controller = _StateController(directory, state)
    controller.write()
    return _run_state_machine(normalized, controller, env, Path(repo_root).resolve(), runner or _ProductionRunner(registry))


def list_workflows(env: Mapping[str, str]) -> list[dict[str, Any]]:
    root = _workflow_root(env)
    if not root.is_dir():
        return []
    values: list[dict[str, Any]] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            state = _load_json(directory / "state.json")
        except WorkflowRunError:
            state = {"workflowId": directory.name, "status": "corrupt", "name": None, "updatedAt": None}
        values.append(state)
    return sorted(values, key=lambda value: str(value.get("updatedAt") or ""), reverse=True)


def show_workflow(env: Mapping[str, str], workflow_id: str) -> dict[str, Any]:
    return _load_json(_find_workflow_dir(env, workflow_id) / "state.json")


def cancel_workflow(env: Mapping[str, str], workflow_id: str) -> dict[str, Any]:
    directory = _find_workflow_dir(env, workflow_id)
    active = _runner_active(directory)
    with _WorkflowFileLock(directory, "state.lock"):
        state = _load_json(directory / "state.json")
        if state.get("status") in TERMINAL_WORKFLOW_STATES and not active:
            return state
        state["cancellationRequested"] = True
        state["updatedAt"] = utc_now()
        atomic_write_json(directory / "state.json", state)
    pid = state.get("runnerPid")
    if active and type(pid) is int and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    return state
