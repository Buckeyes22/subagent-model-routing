"""Portable, fail-open lifecycle hooks."""

from __future__ import annotations

import json
from typing import Any, Mapping
import uuid

from .process import run_bounded_capture
from .run_store import RunStore, atomic_write_bytes, config_root, ensure_private_directory


MAX_HOOK_OUTPUT_BYTES = 1024 * 1024


class HookRunner:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = dict(env)
        self.config_path = config_root(env) / "hooks.json"
        self._config: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._config is not None:
            return self._config
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._config = value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            self._config = {}
        return self._config

    def __call__(self, event: dict[str, Any], store: RunStore) -> None:
        hooks = self._load().get(event["event"], [])
        if not isinstance(hooks, list):
            return
        try:
            depth = int(self.env.get("SUBAGENT_MODEL_ROUTING_HOOK_DEPTH", "0") or "0")
        except (TypeError, ValueError):
            depth = 0
        if depth >= 3:
            return
        for definition in hooks:
            try:
                self._run_one(definition, event, store, depth)
            except (OSError, TypeError, ValueError):
                # Hooks are fail-open in v0.3: malformed configuration and
                # artifact-write failures must never suppress the sentinel.
                continue

    def _run_one(self, definition: Any, event: dict[str, Any], store: RunStore, depth: int) -> None:
        if not isinstance(definition, dict):
            return
        command = definition.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            return
        timeout = definition.get("timeoutSeconds", 5)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            timeout = 5
        hook_id = str(uuid.uuid4())
        hook_dir = store.artifact("hooks")
        ensure_private_directory(hook_dir)
        child_env = dict(self.env)
        child_env.update(
            {
                "SUBAGENT_MODEL_ROUTING_HOOK_DEPTH": str(depth + 1),
                "SUBAGENT_MODEL_ROUTING_EVENT": event["event"],
                "SUBAGENT_MODEL_ROUTING_DISPATCH_ID": event["dispatchId"],
                "SUBAGENT_MODEL_ROUTING_PROVIDER": event["provider"],
                "SUBAGENT_MODEL_ROUTING_MODEL": event["model"],
            }
        )
        if event.get("workflowId") is not None:
            child_env["SUBAGENT_MODEL_ROUTING_WORKFLOW_ID"] = str(event["workflowId"])
        if event.get("taskId") is not None:
            child_env["SUBAGENT_MODEL_ROUTING_TASK_ID"] = str(event["taskId"])
        try:
            result = run_bounded_capture(
                command,
                env=child_env,
                timeout_seconds=float(timeout),
                max_bytes=MAX_HOOK_OUTPUT_BYTES,
                stdin=(json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8"),
            )
            stdout, stderr = result.stdout, result.stderr
            status = {
                "exitCode": None if result.timed_out else result.returncode,
                "timedOut": result.timed_out,
                "stdoutBytes": result.stdout_bytes,
                "stderrBytes": result.stderr_bytes,
                "stdoutTruncated": result.stdout_truncated,
                "stderrTruncated": result.stderr_truncated,
            }
        except OSError as exc:
            stdout = b""
            stderr = str(exc).encode("utf-8", errors="replace")
            status = {
                "exitCode": None,
                "timedOut": False,
                "stdoutBytes": 0,
                "stderrBytes": len(stderr),
                "stdoutTruncated": False,
                "stderrTruncated": False,
            }
        prefix = f"{event['event']}-{hook_id}"
        atomic_write_bytes(hook_dir / f"{prefix}.stdout.log", stdout)
        atomic_write_bytes(hook_dir / f"{prefix}.stderr.log", stderr)
        atomic_write_bytes(
            hook_dir / f"{prefix}.json",
            (json.dumps(status, sort_keys=True) + "\n").encode("utf-8"),
        )
