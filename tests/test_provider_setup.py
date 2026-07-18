"""Tests for optional provider CLI setup and its checkbox terminal."""

from __future__ import annotations

import io
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import termios
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "runtime"))

from model_routing import provider_setup  # noqa: E402
from model_routing import cli  # noqa: E402


def executable(path: Path, content: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


class FakeResponse:
    def __init__(self, content: bytes, url: str, *, status: int = 200) -> None:
        self.content = content
        self.url = url
        self.status = status
        self.offset = 0

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, size: int) -> bytes:
        chunk = self.content[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class FakeSession:
    def __init__(self, keys: list[str], *, term: str = "xterm") -> None:
        self.keys = iter(keys)
        self.term = term
        self.output = ""
        self.paints: list[tuple[str, ...]] = []
        self.descriptor = 9
        self.input_mode_restored = False

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read_key(self) -> str:
        return next(self.keys)

    def write(self, text: str) -> None:
        self.output += text

    def repaint(self, lines: tuple[str, ...]) -> None:
        self.paints.append(lines)

    def finish_repaint(self) -> None:
        self.output += "\n"

    def restore_input_mode(self) -> None:
        self.input_mode_restored = True


class ManifestTests(unittest.TestCase):
    def manifest(self) -> dict[str, object]:
        return json.loads((ROOT / "config/provider-installers.json").read_text(encoding="utf-8"))

    def load_with(self, value: dict[str, object]) -> tuple[provider_setup.ProviderInstallSpec, ...]:
        with mock.patch.object(provider_setup, "_load_json", return_value=value):
            return provider_setup.load_install_specs(ROOT, system_name="Linux")

    def test_manifest_covers_registry_with_first_party_https_recipes(self) -> None:
        specs = provider_setup.load_install_specs(ROOT, system_name="Linux")
        self.assertEqual(("codex", "claude", "grok", "kimi", "opencode"), tuple(spec.provider_id for spec in specs))
        for spec in specs:
            with self.subTest(provider=spec.provider_id):
                self.assertTrue(spec.recipe.installer_url.startswith("https://"))
                self.assertIn(spec.recipe.interpreter[0], {"bash", "sh"})
                self.assertIn(spec.recipe.installer_url.split("/", 3)[2], spec.allowed_redirect_hosts)
                self.assertTrue(spec.auth_args)
                self.assertTrue(spec.verify_args)
        self.assertEqual(4, sum(spec.recipe.sha256 is not None for spec in specs))
        self.assertIsNone(next(spec for spec in specs if spec.provider_id == "kimi").recipe.sha256)

    def test_missing_provider_is_rejected(self) -> None:
        manifest = self.manifest()
        del manifest["providers"]["kimi"]  # type: ignore[attr-defined,index]
        with self.assertRaisesRegex(provider_setup.ProviderSetupError, "exactly match"):
            self.load_with(manifest)

    def test_extra_provider_is_rejected(self) -> None:
        manifest = self.manifest()
        manifest["providers"]["unexpected"] = manifest["providers"]["codex"]  # type: ignore[index]
        with self.assertRaisesRegex(provider_setup.ProviderSetupError, "exactly match"):
            self.load_with(manifest)

    def test_registry_drift_is_rejected(self) -> None:
        registry = json.loads((ROOT / "config/provider-registry.json").read_text(encoding="utf-8"))
        del registry["providers"]["kimi"]
        with mock.patch.object(provider_setup, "load_registry", return_value=registry):
            with self.assertRaisesRegex(provider_setup.ProviderSetupError, "exactly match"):
                provider_setup.load_install_specs(ROOT, system_name="Linux")

    def test_unsafe_scheme_is_rejected(self) -> None:
        manifest = self.manifest()
        manifest["providers"]["codex"]["platforms"]["linux"]["installerUrl"] = "http://example.com/x"  # type: ignore[index]
        with self.assertRaisesRegex(provider_setup.ProviderSetupError, "must use https"):
            self.load_with(manifest)

    def test_unapproved_interpreter_is_rejected(self) -> None:
        manifest = self.manifest()
        manifest["providers"]["codex"]["platforms"]["linux"]["interpreter"] = ["python"]  # type: ignore[index]
        with self.assertRaisesRegex(provider_setup.ProviderSetupError, "unsupported interpreter"):
            self.load_with(manifest)

    def test_initial_installer_host_must_be_allowlisted(self) -> None:
        manifest = self.manifest()
        manifest["providers"]["codex"]["allowedRedirectHosts"] = ["example.com"]  # type: ignore[index]
        with self.assertRaisesRegex(provider_setup.ProviderSetupError, "installer host"):
            self.load_with(manifest)

    def test_invalid_redirect_hostname_is_rejected(self) -> None:
        manifest = self.manifest()
        manifest["providers"]["codex"]["allowedRedirectHosts"] = ["chatgpt.com", "bad..host"]  # type: ignore[index]
        with self.assertRaisesRegex(provider_setup.ProviderSetupError, "invalid host"):
            self.load_with(manifest)

    def test_registry_display_name_and_override_are_reused(self) -> None:
        specs = provider_setup.load_install_specs(ROOT, system_name="Darwin")
        codex = specs[0]
        self.assertEqual("OpenAI Codex", codex.display_name)
        self.assertEqual("CODEX_BIN", codex.binary_override_env)

    def test_unsupported_native_windows_is_explicit(self) -> None:
        with self.assertRaisesRegex(provider_setup.ProviderSetupError, "Windows through WSL.*https://"):
            provider_setup.load_install_specs(ROOT, system_name="Windows")


class DetectionAndSelectionTests(unittest.TestCase):
    def specs(self) -> tuple[provider_setup.ProviderInstallSpec, ...]:
        return provider_setup.load_install_specs(ROOT, system_name="Linux")

    def test_detection_respects_path_fallback_and_binary_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            binary_dir = root / "bin"
            home.mkdir()
            codex = executable(binary_dir / "codex")
            custom_kimi = executable(root / "custom-kimi")
            env = {
                "HOME": str(home),
                "PATH": str(binary_dir),
                "KIMI_BIN": str(custom_kimi),
            }
            rows = {row.provider_id: row for row in provider_setup.detect_provider_rows(self.specs(), env)}
            self.assertEqual(str(codex.resolve()), rows["codex"].installed_path)
            self.assertEqual(str(custom_kimi.resolve()), rows["kimi"].installed_path)
            self.assertFalse(rows["claude"].installed)

    def test_detection_refreshes_existing_common_user_bin_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            opencode = executable(home / ".opencode/bin/opencode")
            rows = provider_setup.detect_provider_rows(
                self.specs(), {"HOME": str(home), "PATH": "/nonexistent"}
            )
            by_id = {row.provider_id: row for row in rows}
            self.assertEqual(str(opencode.resolve()), by_id["opencode"].installed_path)

    def test_selection_skips_installed_rows_and_toggles_only_missing(self) -> None:
        rows = (
            provider_setup.ProviderRow("codex", "Codex", "/bin/codex"),
            provider_setup.ProviderRow("claude", "Claude", None),
            provider_setup.ProviderRow("grok", "Grok", "/bin/grok"),
            provider_setup.ProviderRow("kimi", "Kimi", None),
        )
        state = provider_setup.initial_selection(rows)
        self.assertEqual(1, state.cursor)
        state = provider_setup.toggle_selection(state)
        self.assertEqual(("claude",), provider_setup.selected_provider_ids(state))
        state = provider_setup.move_selection(state, 1)
        self.assertEqual(3, state.cursor)
        state = provider_setup.toggle_selection(state)
        self.assertEqual(("claude", "kimi"), provider_setup.selected_provider_ids(state))
        state = provider_setup.move_selection(state, 1)
        self.assertEqual(1, state.cursor)

    def test_checkbox_controls_and_cancel(self) -> None:
        rows = (
            provider_setup.ProviderRow("codex", "Codex", None),
            provider_setup.ProviderRow("claude", "Claude", None),
        )
        session = FakeSession([" ", "DOWN", " ", "\r"])
        selected = provider_setup.choose_providers(rows, session, no_color=True)  # type: ignore[arg-type]
        self.assertEqual(("codex", "claude"), selected)
        self.assertIn("[x] Codex", "\n".join(session.paints[-1]))

        cancelled = provider_setup.choose_providers(
            rows, FakeSession(["ESC"]), no_color=True  # type: ignore[arg-type]
        )
        self.assertIsNone(cancelled)

    def test_enter_with_no_selection_is_clean_skip(self) -> None:
        rows = (provider_setup.ProviderRow("codex", "Codex", None),)
        selected = provider_setup.choose_providers(
            rows, FakeSession(["\n"]), no_color=True  # type: ignore[arg-type]
        )
        self.assertEqual((), selected)

    def test_confirmation_defaults_to_no_and_shows_sources(self) -> None:
        spec = self.specs()[0]
        rejected = FakeSession(["\n"])
        self.assertFalse(
            provider_setup.confirm_selection([spec], rejected, dry_run=False)  # type: ignore[arg-type]
        )
        self.assertIn("chatgpt.com", rejected.output)
        self.assertIn("SHA-256", rejected.output)
        self.assertIn("No login", rejected.output)

        kimi = next(spec for spec in self.specs() if spec.provider_id == "kimi")
        kimi_rejected = FakeSession(["\n"])
        self.assertFalse(
            provider_setup.confirm_selection([kimi], kimi_rejected, dry_run=False)  # type: ignore[arg-type]
        )
        self.assertIn("WARNING: no pinned checksum", kimi_rejected.output)

    def test_tty_selector_reads_arrows_space_enter_and_restores_attributes(self) -> None:
        master, slave = pty.openpty()
        stop_drain = threading.Event()

        def drain_master() -> None:
            while not stop_drain.is_set():
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        os.read(master, 4096)
                    except OSError:
                        return

        drain_thread = threading.Thread(target=drain_master, daemon=True)
        drain_thread.start()
        try:
            tty_path = os.ttyname(slave)
            before = termios.tcgetattr(slave)
            with provider_setup.TtySession(tty_path, term="xterm") as session:
                os.write(master, b" \x1b[B \r")
                selected = provider_setup.choose_providers(
                    (
                        provider_setup.ProviderRow("codex", "Codex", None),
                        provider_setup.ProviderRow("claude", "Claude", None),
                    ),
                    session,
                    no_color=True,
                )
                self.assertEqual(("codex", "claude"), selected)
                session.restore_input_mode()
                self.assertEqual(before, termios.tcgetattr(slave))
            self.assertEqual(before, termios.tcgetattr(slave))
        finally:
            stop_drain.set()
            drain_thread.join(timeout=1)
            os.close(master)
            os.close(slave)

    def test_tty_ctrl_c_restores_attributes(self) -> None:
        master, slave = pty.openpty()
        try:
            tty_path = os.ttyname(slave)
            before = termios.tcgetattr(slave)
            with self.assertRaises(provider_setup.TerminalSignal):
                with provider_setup.TtySession(tty_path, term="xterm"):
                    os.kill(os.getpid(), signal.SIGINT)
            self.assertEqual(before, termios.tcgetattr(slave))
        finally:
            os.close(master)
            os.close(slave)


class DownloadAndInstallTests(unittest.TestCase):
    def specs(self) -> tuple[provider_setup.ProviderInstallSpec, ...]:
        return provider_setup.load_install_specs(ROOT, system_name="Linux")

    def test_download_accepts_only_bounded_shebang_from_allowlisted_redirect(self) -> None:
        spec = self.specs()[0]
        content = b"#!/bin/sh\necho ok\n"
        spec = replace(
            spec,
            recipe=replace(spec.recipe, sha256=hashlib.sha256(content).hexdigest()),
        )
        response = FakeResponse(
            content,
            "https://release-assets.githubusercontent.com/file?signature=secret#fragment",
        )
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(provider_setup, "build_opener", return_value=opener) as build:
            downloaded = provider_setup.download_installer(spec)
        self.assertEqual(content, downloaded.content)
        self.assertEqual("https://release-assets.githubusercontent.com/file", downloaded.resolved_url)
        self.assertNotIn("secret", downloaded.resolved_url)
        self.assertEqual(hashlib.sha256(content).hexdigest(), downloaded.sha256)
        request = opener.open.call_args.args[0]
        self.assertEqual(spec.recipe.installer_url, request.full_url)
        handler = build.call_args.args[0]
        self.assertEqual(spec.allowed_redirect_hosts, handler.allowed_hosts)

    def test_each_redirect_hop_is_rejected_before_request(self) -> None:
        spec = self.specs()[0]
        handler = provider_setup.ApprovedRedirectHandler(spec.allowed_redirect_hosts)
        with self.assertRaisesRegex(provider_setup.InstallerDownloadError, "unapproved host"):
            handler.redirect_request(
                provider_setup.Request(spec.recipe.installer_url),
                None,
                302,
                "Found",
                {},
                "https://evil.example/install.sh",
            )

    def test_download_rejects_changed_content_when_checksum_is_pinned(self) -> None:
        spec = self.specs()[0]
        response = FakeResponse(b"#!/bin/sh\necho changed\n", spec.recipe.installer_url)
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(provider_setup, "build_opener", return_value=opener):
            with self.assertRaisesRegex(provider_setup.InstallerDownloadError, "SHA-256"):
                provider_setup.download_installer(spec)

    def test_download_rejects_unapproved_redirect_empty_and_non_script_content(self) -> None:
        spec = self.specs()[0]
        cases = (
            (FakeResponse(b"#!/bin/sh\n", "https://evil.example/install"), "unapproved host"),
            (FakeResponse(b"", spec.recipe.installer_url), "empty"),
            (FakeResponse(b"not a script", spec.recipe.installer_url), "shebang"),
        )
        for response, message in cases:
            opener = mock.Mock()
            opener.open.return_value = response
            with self.subTest(message=message), mock.patch.object(
                provider_setup, "build_opener", return_value=opener
            ):
                with self.assertRaisesRegex(provider_setup.InstallerDownloadError, message):
                    provider_setup.download_installer(spec)

    def test_download_failure_result_links_first_party_documentation(self) -> None:
        spec = self.specs()[0]
        with tempfile.TemporaryDirectory() as directory:
            results = provider_setup.install_selected(
                [spec],
                {"HOME": directory, "PATH": "/nonexistent"},
                1,
                downloader=mock.Mock(
                    side_effect=provider_setup.InstallerDownloadError("source unavailable")
                ),
            )
        self.assertEqual("failed", results[0].status)
        self.assertIn(spec.documentation_url, results[0].message)

    def test_download_rejects_oversized_content(self) -> None:
        spec = self.specs()[0]
        content = b"#!" + b"x" * provider_setup.MAX_INSTALLER_BYTES
        response = FakeResponse(content, spec.recipe.installer_url)
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(provider_setup, "build_opener", return_value=opener):
            with self.assertRaisesRegex(provider_setup.InstallerDownloadError, "size limit"):
                provider_setup.download_installer(spec)

    def test_install_continues_after_failure_verifies_success_and_cleans_tempfiles(self) -> None:
        specs = self.specs()
        selected = (specs[0], specs[3])  # codex fails, kimi succeeds
        seen_paths: list[Path] = []
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}

            def runner(argv: list[str], child_env: dict[str, str], _fd: int) -> int:
                path = Path(argv[-1])
                seen_paths.append(path)
                self.assertEqual(0o600, path.stat().st_mode & 0o777)
                if "codex" in path.name:
                    return 7
                executable(Path(child_env["HOME"]) / ".local/bin/kimi")
                return 0

            results = provider_setup.install_selected(
                selected,
                env,
                1,
                downloader=lambda _spec: b"#!/bin/sh\n",
                installer_runner=runner,  # type: ignore[arg-type]
                verifier=lambda *_args: (True, "verified"),
            )
        self.assertEqual(("failed", "installed"), tuple(result.status for result in results))
        self.assertIn("exited 7", results[0].message)
        self.assertTrue(all(not path.exists() for path in seen_paths))

    def test_existing_binary_is_never_downloaded_or_reinstalled(self) -> None:
        spec = self.specs()[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary_dir = root / "bin"
            executable(binary_dir / "codex")
            downloader = mock.Mock(side_effect=AssertionError("must not download"))
            results = provider_setup.install_selected(
                [spec],
                {"HOME": str(root / "home"), "PATH": str(binary_dir)},
                1,
                downloader=downloader,
            )
        self.assertEqual("already-installed", results[0].status)
        downloader.assert_not_called()

    def test_dry_run_performs_no_download_or_execution(self) -> None:
        spec = self.specs()[0]
        with tempfile.TemporaryDirectory() as directory:
            downloader = mock.Mock(side_effect=AssertionError("must not download"))
            runner = mock.Mock(side_effect=AssertionError("must not run"))
            results = provider_setup.install_selected(
                [spec],
                {"HOME": directory, "PATH": "/nonexistent"},
                1,
                dry_run=True,
                downloader=downloader,
                installer_runner=runner,
            )
        self.assertEqual("dry-run", results[0].status)
        self.assertIn(spec.recipe.installer_url, results[0].message)
        downloader.assert_not_called()
        runner.assert_not_called()

    def test_runner_uses_argv_and_never_shell_true(self) -> None:
        process = mock.Mock()
        process.wait.return_value = 0
        with mock.patch.object(provider_setup.subprocess, "Popen", return_value=process) as popen:
            result = provider_setup.run_installer(["sh", "/tmp/installer.sh"], {"PATH": "/bin"}, 1)
        self.assertEqual(0, result)
        self.assertEqual(["sh", "/tmp/installer.sh"], popen.call_args.args[0])
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_runner_bounds_term_and_kill_waits_after_timeout(self) -> None:
        process = mock.Mock(pid=4321)
        process.wait.side_effect = (
            subprocess.TimeoutExpired(["sh"], provider_setup.INSTALL_TIMEOUT_SECONDS),
            subprocess.TimeoutExpired(["sh"], 2),
            subprocess.TimeoutExpired(["sh"], 2),
        )
        with mock.patch.object(provider_setup.subprocess, "Popen", return_value=process), mock.patch.object(
            provider_setup.os, "killpg"
        ) as killpg:
            result = provider_setup.run_installer(["sh", "/tmp/installer.sh"], {"PATH": "/bin"}, 1)
        self.assertEqual(124, result)
        self.assertEqual(
            [mock.call(4321, signal.SIGTERM), mock.call(4321, signal.SIGKILL)],
            killpg.call_args_list,
        )
        self.assertEqual(
            [
                mock.call(timeout=provider_setup.INSTALL_TIMEOUT_SECONDS),
                mock.call(timeout=2),
                mock.call(timeout=2),
            ],
            process.wait.call_args_list,
        )

    def test_interruption_propagates_and_removes_private_tempfile(self) -> None:
        spec = self.specs()[0]
        seen_path: Path | None = None

        def interrupted_runner(argv: list[str], _env: dict[str, str], _fd: int) -> int:
            nonlocal seen_path
            seen_path = Path(argv[-1])
            self.assertEqual(0o600, seen_path.stat().st_mode & 0o777)
            raise provider_setup.TerminalSignal(signal.SIGINT)

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(provider_setup.TerminalSignal):
                provider_setup.install_selected(
                    [spec],
                    {"HOME": directory, "PATH": "/nonexistent"},
                    1,
                    downloader=lambda _spec: b"#!/bin/sh\n",
                    installer_runner=interrupted_runner,  # type: ignore[arg-type]
                )
        self.assertIsNotNone(seen_path)
        assert seen_path is not None
        self.assertFalse(seen_path.exists())


class SetupOrchestrationTests(unittest.TestCase):
    def test_cli_setup_command_maps_manifest_or_tty_errors_to_exit_two(self) -> None:
        with mock.patch.object(
            cli,
            "run_provider_setup",
            side_effect=provider_setup.ProviderSetupError("no terminal"),
        ), mock.patch.object(cli.sys, "stderr", io.StringIO()) as stderr:
            result = cli.main(["setup", "providers", "--dry-run", "--no-color"])
        self.assertEqual(2, result)
        self.assertIn("no terminal", stderr.getvalue())

    def test_all_installed_succeeds_without_opening_tty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary_dir = root / "bin"
            for name in ("codex", "claude", "grok", "kimi", "opencode"):
                executable(binary_dir / name)
            output = io.StringIO()
            result = provider_setup.run_provider_setup(
                ROOT,
                {"HOME": str(root / "home"), "PATH": str(binary_dir)},
                tty_path=str(root / "missing-tty"),
                output=output,
            )
        self.assertEqual(0, result)
        self.assertIn("All five provider CLIs", output.getvalue())

    def test_missing_providers_without_tty_is_an_invocation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(provider_setup.ProviderSetupError, "interactive terminal"):
                provider_setup.run_provider_setup(
                    ROOT,
                    {"HOME": directory, "PATH": "/nonexistent"},
                    tty_path=str(Path(directory) / "missing-tty"),
                )

    def test_full_dry_run_selection_uses_no_network(self) -> None:
        fake = FakeSession([" ", "\r", "y"])
        downloader = mock.Mock(side_effect=AssertionError("must not download"))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            provider_setup, "TtySession", return_value=fake
        ):
            result = provider_setup.run_provider_setup(
                ROOT,
                {"HOME": directory, "PATH": "/nonexistent", "TERM": "xterm"},
                dry_run=True,
                downloader=downloader,
            )
        self.assertEqual(0, result)
        self.assertIn("dry-run", fake.output)
        self.assertTrue(fake.input_mode_restored)
        downloader.assert_not_called()

    def test_ctrl_c_maps_to_exit_130(self) -> None:
        fake = FakeSession([])
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            provider_setup, "TtySession", return_value=fake
        ), mock.patch.object(
            fake, "read_key", side_effect=provider_setup.TerminalSignal(signal.SIGINT)
        ):
            result = provider_setup.run_provider_setup(
                ROOT,
                {"HOME": directory, "PATH": "/nonexistent", "TERM": "xterm"},
            )
        self.assertEqual(130, result)


if __name__ == "__main__":
    unittest.main()
