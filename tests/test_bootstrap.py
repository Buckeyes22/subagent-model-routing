"""Offline tests for bootstrap provider-menu policy and result handling."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import subprocess
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap.sh"


def write_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


class BootstrapSandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.clone = root / "clone"
        self.destination = root / "installed"
        self.fake_bin = root / "bin"
        self.log = root / "calls.log"
        self.router = root / "fake-model-routing"
        self.home.mkdir()
        (self.clone / ".git").mkdir(parents=True)
        (self.clone / "scripts").mkdir()
        self.fake_bin.mkdir()

        write_executable(
            self.fake_bin / "git",
            """#!/bin/sh
printf 'git %s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"remote get-url origin")
    printf '%s\n' "${FAKE_GIT_ORIGIN:-${SUBAGENT_MODEL_ROUTING_REPO_URL:-https://github.com/Buckeyes22/subagent-model-routing}}"
    ;;
  *"rev-parse --verify HEAD") printf '%s\n' '0123456789abcdef0123456789abcdef01234567' ;;
esac
exit 0
""",
        )
        write_executable(
            self.clone / "scripts/install.sh",
            """#!/bin/bash
set -euo pipefail
destination="${1:?test destination required}"
mkdir -p "$destination"
cp "$FAKE_ROUTER" "$destination/model-routing"
chmod +x "$destination/model-routing"
printf 'installer %s\n' "$destination" >> "$CALL_LOG"
""",
        )
        write_executable(
            self.router,
            """#!/bin/bash
set -euo pipefail
printf 'router %s\n' "$*" >> "$CALL_LOG"
if [ "${1:-} ${2:-}" = "setup providers" ]; then
  if [ -n "${INSTALL_CLIENT_AFTER_SETUP:-}" ]; then
    mkdir -p "$HOME/.local/bin"
    client="$HOME/.local/bin/$INSTALL_CLIENT_AFTER_SETUP"
    printf '%s\n' '#!/bin/sh' 'printf "client %s\\n" "$*" >> "$CALL_LOG"' 'exit 0' > "$client"
    chmod +x "$client"
  fi
  exit "${SETUP_EXIT:-0}"
fi
exit 0
""",
        )

    def environment(self, **overrides: str) -> dict[str, str]:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.fake_bin}:/usr/bin:/bin",
            "TERM": "xterm",
            "CALL_LOG": str(self.log),
            "FAKE_ROUTER": str(self.router),
            "SUBAGENT_MODEL_ROUTING_HOME": str(self.clone),
            "SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR": str(self.destination),
            "SETUP_EXIT": "0",
        }
        env.update(overrides)
        return env

    def calls(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def run_non_tty(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["/bin/bash", str(BOOTSTRAP), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env or self.environment(),
            check=False,
            timeout=20,
        )

    def run_pty(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        master, slave = pty.openpty()

        def make_controlling_terminal() -> None:
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        process = subprocess.Popen(
            ["/bin/bash", str(BOOTSTRAP), *arguments],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env or self.environment(),
            preexec_fn=make_controlling_terminal,
            close_fds=True,
        )
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 20
        try:
            while process.poll() is None and time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        break
            if process.poll() is None:
                process.kill()
                self.fail("bootstrap PTY test timed out")
            while True:
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output.extend(chunk)
        finally:
            os.close(master)
            process.wait(timeout=5)
        return process.returncode, output.decode("utf-8", errors="replace").replace("\r", "")


class BootstrapTests(unittest.TestCase):
    def test_help_documents_provider_menu_flags(self) -> None:
        result = subprocess.run(
            ["/bin/bash", str(BOOTSTRAP), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        output = result.stdout.decode()
        self.assertIn("--provider-menu", output)
        self.assertIn("--no-provider-menu", output)
        self.assertIn("--ref", output)
        self.assertIn("v0.6.0", output)

    def test_default_release_ref_is_fetched_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty()
            calls = sandbox.calls()
        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertIn("fetch --depth 1 origin v0.6.0", calls)
        self.assertIn("checkout --detach FETCH_HEAD", calls)
        self.assertLess(calls.index("checkout --detach"), calls.index("installer "))

    def test_explicit_ref_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty("--ref", "main")
            calls = sandbox.calls()
        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertIn("fetch --depth 1 origin main", calls)

    def test_existing_clone_with_wrong_origin_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty(
                env=sandbox.environment(FAKE_GIT_ORIGIN="https://example.invalid/wrong")
            )
            calls = sandbox.calls()
        self.assertEqual(1, result.returncode)
        self.assertIn("origin does not match", result.stderr.decode())
        self.assertNotIn("installer ", calls)

    def test_invalid_ref_is_rejected_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty("--ref", "-bad")
            calls = sandbox.calls()
        self.assertEqual(2, result.returncode)
        self.assertIn("invalid release tag", result.stderr.decode())
        self.assertNotIn("installer ", calls)

    def test_conflicting_flags_fail_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty("--provider-menu", "--no-provider-menu")
        self.assertEqual(2, result.returncode)
        self.assertIn("cannot be combined", result.stderr.decode())
        self.assertEqual("", sandbox.calls())

    def test_non_tty_auto_mode_skips_without_calling_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty()
            calls = sandbox.calls()
        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertNotIn("router setup providers", calls)
        self.assertIn("no interactive terminal", result.stdout.decode())
        self.assertIn("setup providers", result.stdout.decode())

    def test_no_provider_menu_skips_even_with_tty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            returncode, output = sandbox.run_pty("--no-provider-menu")
            calls = sandbox.calls()
        self.assertEqual(0, returncode, output)
        self.assertNotIn("router setup providers", calls)

    def test_forced_menu_requires_a_tty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty("--provider-menu")
        self.assertEqual(2, result.returncode)
        self.assertIn("requires an interactive terminal", result.stderr.decode())

    def test_term_dumb_auto_mode_skips_with_tty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            returncode, output = sandbox.run_pty(env=sandbox.environment(TERM="dumb"))
            calls = sandbox.calls()
        self.assertEqual(0, returncode, output)
        self.assertNotIn("router setup providers", calls)
        self.assertIn("TERM=dumb", output)

    def test_partial_setup_failure_continues_registration_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            returncode, output = sandbox.run_pty(env=sandbox.environment(SETUP_EXIT="1"))
            calls = sandbox.calls()
        self.assertEqual(1, returncode, output)
        self.assertIn("router setup providers", calls)
        self.assertIn("continuing bootstrap", output)
        self.assertIn("Plugin registration commands", output)
        self.assertIn("Next steps", output)

    def test_forced_setup_invocation_error_is_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            returncode, output = sandbox.run_pty(
                "--provider-menu", env=sandbox.environment(SETUP_EXIT="2")
            )
        self.assertEqual(2, returncode, output)
        self.assertNotIn("Plugin registration commands", output)

    def test_newly_installed_claude_is_detected_for_same_run_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            env = sandbox.environment(INSTALL_CLIENT_AFTER_SETUP="claude")
            returncode, output = sandbox.run_pty("--register", env=env)
            calls = sandbox.calls()
        self.assertEqual(0, returncode, output)
        self.assertIn("claude CLI detected", output)
        self.assertIn("client plugin marketplace add", calls)
        self.assertIn("client plugin install", calls)
        self.assertIn("claude auth login", output)
        self.assertNotIn("    codex login", output)
        self.assertIn("Missing provider CLIs: codex, grok, kimi, opencode", output)

    def test_unknown_flag_remains_an_invocation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = BootstrapSandbox(Path(directory))
            result = sandbox.run_non_tty("--wat")
        self.assertEqual(2, result.returncode)
        self.assertIn("unknown argument", result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
