#!/usr/bin/python3
"""Deterministic fake coding-agent CLI used by shim contract tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import subprocess


def _write_bytes(env_name: str, data: bytes) -> None:
    target = os.environ.get(env_name)
    if target:
        Path(target).write_bytes(data)


def main() -> int:
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "run" and args[1] == "--help":
        sys.stdout.write(os.environ.get("FAKE_HELP", ""))
        return int(os.environ.get("FAKE_HELP_EXIT", "0"))

    _write_bytes("FAKE_ARGS_FILE", b"\0".join(arg.encode() for arg in args))
    _write_bytes("FAKE_STDIN_FILE", sys.stdin.buffer.read())

    env_target = os.environ.get("FAKE_ENV_FILE")
    if env_target:
        keys = [
            "OPENCODE_ENABLE_TELEMETRY",
            "OPENCODE_OTLP_PROTOCOL",
            "OPENCODE_OTLP_ENDPOINT",
            "OPENCODE_RESOURCE_ATTRIBUTES",
            "OTEL_RESOURCE_ATTRIBUTES",
            "KIMI_CODE_NO_AUTO_UPDATE",
        ]
        Path(env_target).write_text(
            json.dumps({key: os.environ.get(key) for key in keys}, sort_keys=True),
            encoding="utf-8",
        )

    sleep_seconds = float(os.environ.get("FAKE_SLEEP_SECS", "0"))
    child_sleep = float(os.environ.get("FAKE_SPAWN_CHILD_SECS", "0"))
    if child_sleep:
        child = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({child_sleep!r})"])
        child_pid_file = os.environ.get("FAKE_CHILD_PID_FILE")
        if child_pid_file:
            Path(child_pid_file).write_text(str(child.pid), encoding="ascii")
    if sleep_seconds:
        time.sleep(sleep_seconds)

    relative_write = os.environ.get("FAKE_WRITE_RELATIVE")
    if relative_write:
        target = Path(relative_write)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(os.environ.get("FAKE_WRITE_CONTENT", "fake edit\n"), encoding="utf-8")

    sys.stdout.write(os.environ.get("FAKE_STDOUT", "fake-provider\n"))
    sys.stderr.write(os.environ.get("FAKE_STDERR", ""))
    return int(os.environ.get("FAKE_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
