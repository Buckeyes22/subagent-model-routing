"""Helpers for exercising the public Bash shim contract in isolated sandboxes."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fake_provider.py"
SHIMS = {
    "codex": ROOT / "scripts" / "codex-shim.sh",
    "claude": ROOT / "scripts" / "claude-shim.sh",
    "grok": ROOT / "scripts" / "grok-shim.sh",
    "kimi": ROOT / "scripts" / "kimi-shim.sh",
    "opencode": ROOT / "scripts" / "opencode-shim.sh",
}

SUPPORT_COMMANDS = ("cat", "date", "dirname", "git", "head", "mkdir", "sed")


class ShimSandbox:
    def __init__(self, *, include_timeout: bool = True) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="model-routing-shim-test-")
        self.root = Path(self._temp.name)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        self.ledger = self.root / "ledger" / "observations.jsonl"
        self.state = self.root / "state"
        self.config = self.root / "config"
        self.args_file = self.root / "args.bin"
        self.stdin_file = self.root / "stdin.bin"
        self.env_file = self.root / "env.json"
        for command in SUPPORT_COMMANDS:
            self._link_system_command(command)
        if include_timeout:
            self._link_timeout()
        self._link_interpreter()

    def cleanup(self) -> None:
        self._temp.cleanup()

    def _link_system_command(self, command: str) -> None:
        source = shutil.which(command)
        if not source:
            raise RuntimeError(f"required test command not found: {command}")
        (self.bin / command).symlink_to(source)

    def _link_timeout(self) -> None:
        # The shims accept either GNU name, so the sandbox must too. Stock
        # macOS ships neither, and Homebrew coreutils can expose only the
        # g-prefixed one; requiring bare `timeout` failed the harness on hosts
        # where the shim itself would have worked.
        for candidate in ("timeout", "gtimeout"):
            source = shutil.which(candidate)
            if source:
                (self.bin / "timeout").symlink_to(source)
                return
        raise RuntimeError(
            "required test command not found: timeout or gtimeout "
            "(brew install coreutils provides gtimeout)"
        )

    def _link_interpreter(self) -> None:
        # The shims exec a python3 to reach the shared runtime, so the sandbox
        # has to supply one exactly as it supplies timeout(1). Link the
        # interpreter running the suite rather than resolving python3 from the
        # host: `command -v python3` finds nothing on this PATH, so the shim
        # would fall back to /usr/bin/python3, which is 3.12 on the Linux
        # runners but 3.9.6 on every macOS. That difference decided whether
        # these tests exercised the shim contract or the runtime's version
        # guard, purely by host.
        (self.bin / "python3").symlink_to(sys.executable)

    def install_provider(self, provider: str) -> Path:
        target = self.bin / provider
        shutil.copy2(FIXTURE, target)
        target.chmod(0o755)
        return target

    def prompt(self, text: str = "test prompt\n") -> Path:
        target = self.root / "prompt.md"
        target.write_text(text, encoding="utf-8")
        return target

    def environment(self, **overrides: str) -> dict[str, str]:
        env = {
            "HOME": str(self.home),
            "PATH": str(self.bin),
            "SUBAGENT_MODEL_ROUTING_LEDGER": str(self.ledger),
            "XDG_STATE_HOME": str(self.state),
            "XDG_CONFIG_HOME": str(self.config),
            "FAKE_ARGS_FILE": str(self.args_file),
            "FAKE_STDIN_FILE": str(self.stdin_file),
            "FAKE_ENV_FILE": str(self.env_file),
        }
        env.update(overrides)
        return env

    def run(
        self,
        shim: str,
        args: list[str],
        *,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["/bin/bash", str(SHIMS[shim]), *args],
            input=input_bytes,
            capture_output=True,
            env=env or self.environment(),
            timeout=timeout,
            check=False,
        )

    def ledger_records(self) -> list[dict[str, Any]]:
        if not self.ledger.exists():
            return []
        return [
            json.loads(line)
            for line in self.ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def captured_args(self) -> list[str]:
        if not self.args_file.exists() or not self.args_file.read_bytes():
            return []
        return [part.decode() for part in self.args_file.read_bytes().split(b"\0")]

    def captured_stdin(self) -> bytes:
        return self.stdin_file.read_bytes() if self.stdin_file.exists() else b""

    def captured_env(self) -> dict[str, str | None]:
        if not self.env_file.exists():
            return {}
        return json.loads(self.env_file.read_text(encoding="utf-8"))

    def run_directories(self) -> list[Path]:
        root = self.state / "subagent-model-routing" / "runs"
        return list(root.iterdir()) if root.is_dir() else []
