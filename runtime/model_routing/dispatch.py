"""Shared dispatch state machine and legacy-shim compatibility surface."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Mapping
import uuid

from .errors import UsageError
from .events import EventEmitter
from .hooks import HookRunner
from .process import ProcessResult, run_process
from .providers import get_adapter
from .providers.base import ParsedRequest
from .result import validate_result
from .run_store import RunStore, append_jsonl, state_root, utc_now
from .workspace import (
    UsageConfigurationError,
    WorkspaceError,
    WorkspaceRequest,
    capture_changes,
    prepare_isolated_worktree,
    resolve_workspace,
)


TERMINAL_STATES = {"preflight_failed", "succeeded", "failed", "timed_out", "cancelled", "blocked"}
TRANSITIONS = {
    "created": {"preflighting"},
    "preflighting": {"preflight_failed", "ready", "failed"},
    "ready": {"workspace_preparing", "running", "failed"},
    "workspace_preparing": {"workspace_ready", "failed"},
    "workspace_ready": {"running", "failed"},
    "running": {"succeeded", "failed", "timed_out", "cancelled"},
}


def _legacy_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _ledger_path(env: Mapping[str, str]) -> Path:
    configured = env.get("SUBAGENT_MODEL_ROUTING_LEDGER")
    if configured:
        return Path(configured).expanduser()
    return Path(env.get("HOME", "~")).expanduser() / ".claude" / "subagent-model-routing" / "ledger" / "observations.jsonl"


def _ledger_record(
    env: Mapping[str, str],
    *,
    dispatch_id: str,
    provider: str,
    model: str,
    event: str,
    exit_code: int | None = None,
    wall_seconds: int | None = None,
    outcome: str | None = None,
    supervisor_timeout: bool | None = None,
    workspace: str = "shared",
) -> None:
    record: dict[str, Any] = {
        "ts": _legacy_timestamp(),
        "shim": provider,
        "model": model,
        "event": event,
        "source": "shim",
        "schema_version": 2,
        "dispatch_id": dispatch_id,
        "workflow_id": env.get("SUBAGENT_MODEL_ROUTING_WORKFLOW_ID") or None,
        "task_id": env.get("SUBAGENT_MODEL_ROUTING_TASK_ID") or None,
        "attempt": int(env.get("SUBAGENT_MODEL_ROUTING_ATTEMPT", "1")),
        "workspace": workspace,
    }
    if exit_code is not None:
        record["exit"] = exit_code
    if wall_seconds is not None:
        record["wall_s"] = wall_seconds
    if outcome is not None:
        record["outcome"] = outcome
    if supervisor_timeout is not None:
        record["supervisor_timeout"] = supervisor_timeout
    try:
        append_jsonl(_ledger_path(env), record)
    except OSError:
        pass


def _emit_sentinel(exit_code: int, *, leading_newline: bool) -> None:
    prefix = b"\n" if leading_newline else b""
    sys.stdout.buffer.write(prefix + f"SHIM-DONE exit={exit_code}\n".encode("ascii"))
    sys.stdout.buffer.flush()


def _parse_timeout(raw: str) -> float:
    multipliers = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    suffix = raw[-1:].lower()
    if suffix in multipliers:
        return float(raw[:-1]) * multipliers[suffix]
    return float(raw)


def _gnu_timeout_available(env: Mapping[str, str]) -> bool:
    path = env.get("PATH")
    return bool(shutil.which("timeout", path=path) or shutil.which("gtimeout", path=path))


def _read_prompt(source: str) -> bytes:
    if source == "-":
        return sys.stdin.buffer.read()
    return Path(source).read_bytes()


@dataclass(slots=True)
class RoutingOptions:
    retain_prompt: bool = False
    workspace: str = "shared"
    task_mode: str | None = None
    base: str | None = None


@dataclass(slots=True, frozen=True)
class DispatchContext:
    dispatch_id: str
    workflow_id: str | None
    task_id: str | None
    attempt: int
    effort: str | None


def _dispatch_context(env: Mapping[str, str]) -> DispatchContext:
    raw_dispatch = env.get("SUBAGENT_MODEL_ROUTING_DISPATCH_ID")
    dispatch_id = raw_dispatch or str(uuid.uuid4())
    try:
        uuid.UUID(dispatch_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise UsageError("SUBAGENT_MODEL_ROUTING_DISPATCH_ID must be a UUID") from exc
    workflow_id = env.get("SUBAGENT_MODEL_ROUTING_WORKFLOW_ID") or None
    task_id = env.get("SUBAGENT_MODEL_ROUTING_TASK_ID") or None
    try:
        attempt = int(env.get("SUBAGENT_MODEL_ROUTING_ATTEMPT", "1"))
    except ValueError as exc:
        raise UsageError("SUBAGENT_MODEL_ROUTING_ATTEMPT must be a positive integer") from exc
    if attempt < 1:
        raise UsageError("SUBAGENT_MODEL_ROUTING_ATTEMPT must be a positive integer")
    return DispatchContext(
        dispatch_id=dispatch_id,
        workflow_id=workflow_id,
        task_id=task_id,
        attempt=attempt,
        effort=env.get("SUBAGENT_MODEL_ROUTING_EFFORT") or None,
    )


def _strip_routing_args(argv: list[str]) -> tuple[list[str], RoutingOptions]:
    options = RoutingOptions()
    forwarded: list[str] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--routing-retain-prompt":
            options.retain_prompt = True
            index += 1
            continue
        matched = False
        for flag, field, choices in (
            ("--routing-workspace", "workspace", {"shared", "isolated", "auto"}),
            ("--routing-task-mode", "task_mode", {"read", "write"}),
            ("--routing-base", "base", None),
        ):
            if argument == flag:
                if index + 1 >= len(argv):
                    raise UsageError(f"{flag} requires a value")
                value = argv[index + 1]
                index += 2
                matched = True
            elif argument.startswith(flag + "="):
                value = argument.split("=", 1)[1]
                index += 1
                matched = True
            else:
                continue
            if not value or (choices is not None and value not in choices):
                expected = "|".join(sorted(choices)) if choices else "COMMIT"
                raise UsageError(f"{flag} expects {expected}")
            setattr(options, field, value)
            break
        if matched:
            continue
        if argument.startswith("--routing-"):
            raise UsageError(f"unknown routing option: {argument}")
        else:
            forwarded.append(argument)
        index += 1
    try:
        options.workspace = resolve_workspace(WorkspaceRequest(options.workspace, options.task_mode))
    except UsageConfigurationError as exc:
        raise UsageError(str(exc)) from exc
    return forwarded, options


class Lifecycle:
    def __init__(
        self,
        store: RunStore,
        provider: str,
        model: str,
        emitter: EventEmitter,
        context: DispatchContext | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.model = model
        self.context = context or DispatchContext(store.dispatch_id, None, None, 1, None)
        self.created_at = utc_now()
        self.state = "created"
        self.transitions = [{"state": "created", "timestamp": self.created_at}]
        self._write()
        emitter.emit("dispatch.created")

    def transition(self, state: str) -> None:
        if state not in TRANSITIONS.get(self.state, set()):
            raise RuntimeError(f"invalid dispatch transition {self.state} -> {state}")
        if self.state in TERMINAL_STATES:
            raise RuntimeError(f"terminal dispatch cannot transition from {self.state}")
        self.state = state
        self.transitions.append({"state": state, "timestamp": utc_now()})
        self._write()

    def _write(self) -> None:
        self.store.write_json(
            "run.json",
            {
                "schemaVersion": 1,
                "dispatchId": self.store.dispatch_id,
                "workflowId": self.context.workflow_id,
                "taskId": self.context.task_id,
                "attempt": self.context.attempt,
                "provider": self.provider,
                "model": self.model,
                "state": self.state,
                "createdAt": self.created_at,
                "transitions": self.transitions,
            },
        )


def _base_result(
    store: RunStore,
    lifecycle: Lifecycle,
    request: ParsedRequest,
    *,
    status: str,
    outcome: str,
    exit_code: int,
    started_at: str | None,
    wall_ms: int,
    signal_number: int | None,
    arguments: list[str] | None = None,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finished_at = utc_now()
    stdout_path = store.artifact("stdout.log")
    stderr_path = store.artifact("stderr.log")

    def digest(path: Path) -> dict[str, Any]:
        hasher = hashlib.sha256()
        byte_count = 0
        if path.is_file():
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    hasher.update(chunk)
        return {"bytes": byte_count, "sha256": hasher.hexdigest()}

    return {
        "schemaVersion": 1,
        "dispatchId": store.dispatch_id,
        "workflowId": lifecycle.context.workflow_id,
        "taskId": lifecycle.context.task_id,
        "provider": lifecycle.provider,
        "model": request.model,
        "requestedModel": request.model,
        "effort": lifecycle.context.effort,
        "arguments": arguments or [],
        "providerVersion": None,
        "status": status,
        "outcome": outcome,
        "createdAt": lifecycle.created_at,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "wallMs": wall_ms,
        "exitCode": exit_code,
        "signal": signal_number,
        "timeout": {"seconds": None, "expired": status == "timed_out"},
        "sentinel": {"emitted": True, "exit": exit_code},
        "workspace": workspace or {"mode": "shared", "path": str(Path.cwd()), "baseSha": None, "finalSha": None},
        "output": {"stdout": digest(stdout_path), "stderr": digest(stderr_path)},
        "artifacts": store.artifact_summary(),
        "integration": {"status": "not_applied", "appliedAt": None, "target": None},
    }


def _finish_early(
    *,
    store: RunStore,
    lifecycle: Lifecycle,
    emitter: EventEmitter,
    request: ParsedRequest,
    state: str,
    event: str,
    exit_code: int,
    outcome: str,
    leading_newline: bool,
    started_at: str | None = None,
    arguments: list[str] | None = None,
    workspace: dict[str, Any] | None = None,
) -> int:
    try:
        lifecycle.transition(state)
        result = _base_result(
            store,
            lifecycle,
            request,
            status=state,
            outcome=outcome,
            exit_code=exit_code,
            started_at=started_at,
            wall_ms=0,
            signal_number=None,
            arguments=arguments,
            workspace=workspace,
        )
        validate_result(result)
        store.write_json("result.json", result)
        emitter.emit(event, {"exitCode": exit_code, "outcome": outcome})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"{lifecycle.provider}-shim: cannot finalize run metadata: {exc}", file=sys.stderr)
    finally:
        _emit_sentinel(exit_code, leading_newline=leading_newline)
    return exit_code


def dispatch_legacy(provider_id: str, argv: list[str], *, environ: Mapping[str, str] | None = None) -> int:
    env = dict(os.environ if environ is None else environ)
    adapter = get_adapter(provider_id)
    home = Path(env.get("HOME", "~")).expanduser()
    try:
        context = _dispatch_context(env)
        forwarded, routing = _strip_routing_args(argv)
        request = adapter.parse(forwarded, env, home)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        _emit_sentinel(64, leading_newline=False)
        return 64

    dispatch_id = context.dispatch_id
    existing = RunStore(state_root(env), dispatch_id).path
    if existing.exists():
        print(f"{provider_id}-shim: dispatch ID already exists: {dispatch_id}", file=sys.stderr)
        _emit_sentinel(64, leading_newline=False)
        return 64
    store = RunStore.create(env, dispatch_id)
    store.touch_artifact("stdout.log")
    store.touch_artifact("stderr.log")
    hooks = HookRunner(env)
    emitter = EventEmitter(
        store,
        provider=provider_id,
        model=request.model,
        workflow_id=context.workflow_id,
        task_id=context.task_id,
        callback=hooks,
    )
    lifecycle = Lifecycle(store, provider_id, request.model, emitter, context)
    lifecycle.transition("preflighting")
    emitter.emit("dispatch.preflight_started")

    binary = adapter.resolve_binary(env, home)
    if adapter.preflight_binary and binary is None:
        print(adapter.missing_binary_message(), file=sys.stderr)
        if adapter.missing_binary_ledger == "finished":
            _ledger_record(
                env,
                dispatch_id=dispatch_id,
                provider=provider_id,
                model=request.model,
                event="finished",
                exit_code=127,
                wall_seconds=0,
                outcome="error",
                workspace=routing.workspace,
            )
        store.record_request(request.source, None, retain_prompt=False, error="provider binary unavailable")
        return _finish_early(
            store=store,
            lifecycle=lifecycle,
            emitter=emitter,
            request=request,
            state="preflight_failed",
            event="dispatch.preflight_failed",
            exit_code=127,
            outcome="error",
            leading_newline=False,
            workspace={
                "mode": routing.workspace,
                "path": str(Path.cwd()),
                "baseSha": None,
                "finalSha": None,
            },
        )

    if not _gnu_timeout_available(env):
        print(f"{provider_id}-shim: GNU timeout not found (brew install coreutils provides gtimeout)", file=sys.stderr)
        store.record_request(request.source, None, retain_prompt=False, error="GNU timeout unavailable")
        return _finish_early(
            store=store,
            lifecycle=lifecycle,
            emitter=emitter,
            request=request,
            state="preflight_failed",
            event="dispatch.preflight_failed",
            exit_code=127,
            outcome="error",
            leading_newline=False,
        )

    assert binary is not None
    preflight_data = adapter.preflight(request, binary, env)
    lifecycle.transition("ready")
    emitter.emit("dispatch.preflight_succeeded")

    ledger_started = False
    ledger_started_monotonic = time.monotonic()
    if adapter.start_ledger_before_prompt:
        _ledger_record(
            env,
            dispatch_id=dispatch_id,
            provider=provider_id,
            model=request.model,
            event="started",
            workspace=routing.workspace,
        )
        ledger_started = True

    try:
        prompt = _read_prompt(request.source)
    except OSError:
        print(f"{provider_id}-shim: cannot read {request.source}", file=sys.stderr)
        store.record_request(request.source, None, retain_prompt=False, error="unreadable prompt source")
        _ledger_record(
            env,
            dispatch_id=dispatch_id,
            provider=provider_id,
            model=request.model,
            event="finished",
            exit_code=66,
            wall_seconds=0,
            outcome="error",
            workspace=routing.workspace,
        )
        return _finish_early(
            store=store,
            lifecycle=lifecycle,
            emitter=emitter,
            request=request,
            state="failed",
            event="dispatch.failed",
            exit_code=66,
            outcome="error",
            leading_newline=False,
        )

    store.record_request(request.source, prompt, retain_prompt=routing.retain_prompt)
    if not ledger_started:
        ledger_started_monotonic = time.monotonic()
        _ledger_record(
            env,
            dispatch_id=dispatch_id,
            provider=provider_id,
            model=request.model,
            event="started",
            workspace=routing.workspace,
        )

    lifecycle.transition("workspace_preparing")
    emitter.emit("dispatch.workspace_preparing", {"mode": routing.workspace})
    workspace_path = Path.cwd()
    workspace_result: dict[str, Any] = {
        "mode": "shared",
        "path": str(workspace_path),
        "baseSha": None,
        "finalSha": None,
    }
    worktree_metadata = None
    try:
        if routing.workspace == "isolated":
            worktree_metadata = prepare_isolated_worktree(
                env,
                dispatch_id,
                Path.cwd(),
                base_ref=routing.base,
            )
            workspace_path = Path(worktree_metadata.path)
            workspace_result = {
                "mode": "isolated",
                "path": worktree_metadata.path,
                "baseSha": worktree_metadata.baseSha,
                "finalSha": worktree_metadata.baseSha,
            }
        lifecycle.transition("workspace_ready")
        emitter.emit("dispatch.workspace_ready", {"mode": routing.workspace, "path": str(workspace_path)})
    except WorkspaceError as exc:
        print(f"{provider_id}-shim: workspace preflight failed: {exc}", file=sys.stderr)
        _ledger_record(
            env,
            dispatch_id=dispatch_id,
            provider=provider_id,
            model=request.model,
            event="finished",
            exit_code=1,
            wall_seconds=0,
            outcome="error",
            workspace=routing.workspace,
        )
        return _finish_early(
            store=store,
            lifecycle=lifecycle,
            emitter=emitter,
            request=request,
            state="failed",
            event="dispatch.failed",
            exit_code=1,
            outcome="error",
            leading_newline=False,
            workspace={
                "mode": routing.workspace,
                "path": str(Path.cwd()),
                "baseSha": None,
                "finalSha": None,
            },
        )

    prepared = adapter.prepare(request, binary, prompt, env, preflight_data)
    started_at = utc_now()
    lifecycle.transition("running")
    emitter.emit("dispatch.started", {"arguments": prepared.sanitized_args})

    try:
        timeout_seconds = _parse_timeout(env.get("SHIM_TIMEOUT_SECS", "1140"))
        if timeout_seconds <= 0:
            raise ValueError
    except ValueError:
        timeout_seconds = 0.001

    try:
        process_result = run_process(
            prepared.argv,
            env=prepared.env,
            stdin=prepared.stdin,
            stdout_path=store.artifact("stdout.log"),
            stderr_path=store.artifact("stderr.log"),
            timeout_seconds=timeout_seconds,
            cwd=workspace_path,
            output_callback=None,
        )
    except OSError as exc:
        print(f"{provider_id}-shim: cannot execute {binary}: {exc}", file=sys.stderr)
        process_result = ProcessResult(127, None, False, False, 0, 0, 0)

    wall_seconds = max(0, int(time.monotonic() - ledger_started_monotonic))
    for channel, byte_count in (
        ("stdout", process_result.stdout_bytes),
        ("stderr", process_result.stderr_bytes),
    ):
        if byte_count:
            emitter.emit(
                "dispatch.output",
                {"channel": channel, "bytes": byte_count},
            )
    if process_result.timed_out:
        state, outcome, terminal_event = "timed_out", "timeout", "dispatch.timed_out"
    elif process_result.cancelled:
        state, outcome, terminal_event = "cancelled", "cancelled", "dispatch.cancelled"
    elif process_result.exit_code == 0:
        state, outcome, terminal_event = "succeeded", "ok", "dispatch.succeeded"
    else:
        state, outcome, terminal_event = "failed", "error", "dispatch.failed"
    try:
        _ledger_record(
            env,
            dispatch_id=dispatch_id,
            provider=provider_id,
            model=request.model,
            event="finished",
            exit_code=process_result.exit_code,
            wall_seconds=wall_seconds,
            outcome="timeout" if process_result.exit_code == 124 else "ok" if process_result.exit_code == 0 else "error",
            supervisor_timeout=process_result.timed_out,
            workspace=routing.workspace,
        )
        lifecycle.transition(state)
        if worktree_metadata is not None:
            try:
                changes = capture_changes(env, dispatch_id, metadata=worktree_metadata)
                workspace_result["finalSha"] = changes.finalSha
            except WorkspaceError as exc:
                print(f"{provider_id}-shim: cannot capture isolated changes: {exc}", file=sys.stderr)
        result = _base_result(
            store,
            lifecycle,
            request,
            status=state,
            outcome=outcome,
            exit_code=process_result.exit_code,
            started_at=started_at,
            wall_ms=process_result.wall_ms,
            signal_number=process_result.signal,
            arguments=prepared.sanitized_args,
            workspace=workspace_result,
        )
        result["timeout"] = {"seconds": timeout_seconds, "expired": process_result.timed_out}
        validate_result(result)
        store.write_json("result.json", result)
        emitter.emit(terminal_event, {"exitCode": process_result.exit_code, "outcome": outcome})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"{provider_id}-shim: cannot finalize run metadata: {exc}", file=sys.stderr)
    finally:
        _emit_sentinel(process_result.exit_code, leading_newline=True)
    return process_result.exit_code
