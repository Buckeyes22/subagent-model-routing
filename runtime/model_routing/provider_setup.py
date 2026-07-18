"""Interactive, explicit installation of optional provider CLIs.

The setup surface is deliberately separate from dispatch and doctor.  It reads
only the two repository registries, detects executables, renders a checkbox UI
on ``/dev/tty``, and executes only the first-party installer recipes the user
selected and confirmed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
import hashlib
import hmac
from http.client import HTTPException
import json
import os
from pathlib import Path
import platform
import select
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - the public Bash entrypoint targets Unix/WSL
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

from .process import run_bounded_capture
from .providers import get_adapter
from .registry import RegistryError, load_registry


SUPPORTED_PLATFORMS = frozenset({"darwin", "linux"})
ALLOWED_INTERPRETERS = frozenset({"bash", "sh"})
MAX_INSTALLER_BYTES = 2 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 20.0
DOWNLOAD_TOTAL_SECONDS = 60.0
INSTALL_TIMEOUT_SECONDS = 15 * 60.0
VERIFY_TIMEOUT_SECONDS = 10.0
VERIFY_MAX_BYTES = 64 * 1024
USER_AGENT = "subagent-model-routing-provider-setup/1"
SETUP_DOCS_URL = (
    "https://github.com/Buckeyes22/subagent-model-routing/"
    "blob/main/docs/provider-cli-setup.md#supported-platforms"
)
COMMON_USER_BIN_DIRS = (
    ".local/bin",
    ".codex/bin",
    ".claude/bin",
    ".kimi/bin",
    ".opencode/bin",
    ".grok/bin",
)


class ProviderSetupError(ValueError):
    """The setup manifest, platform, or terminal cannot satisfy the request."""


class InstallerDownloadError(RuntimeError):
    """A first-party installer could not be downloaded or validated."""


class TerminalSignal(KeyboardInterrupt):
    """A signal interrupted the terminal selector."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


class ApprovedRedirectHandler(HTTPRedirectHandler):
    """Reject an installer redirect before requesting an unapproved hop."""

    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        parsed = urlparse(new_url)
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise InstallerDownloadError(
                f"installer redirected to unapproved host {parsed.hostname or '<missing>'}"
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


@dataclass(frozen=True, slots=True)
class PlatformRecipe:
    installer_url: str
    interpreter: tuple[str, ...]
    sha256: str | None


@dataclass(frozen=True, slots=True)
class ProviderInstallSpec:
    provider_id: str
    display_name: str
    binary_override_env: str | None
    documentation_url: str
    recipe: PlatformRecipe
    allowed_redirect_hosts: frozenset[str]
    verify_args: tuple[str, ...]
    auth_args: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderRow:
    provider_id: str
    display_name: str
    installed_path: str | None

    @property
    def installed(self) -> bool:
        return self.installed_path is not None


@dataclass(frozen=True, slots=True)
class SelectionState:
    rows: tuple[ProviderRow, ...]
    cursor: int | None
    selected: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class InstallResult:
    provider_id: str
    status: str
    message: str
    resolved_binary: str | None = None


@dataclass(frozen=True, slots=True)
class InstallerDownload:
    content: bytes
    resolved_url: str
    sha256: str


DownloadFunction = Callable[[ProviderInstallSpec], bytes | InstallerDownload]
InstallerRunner = Callable[[Sequence[str], Mapping[str, str], int], int]
Verifier = Callable[[str, ProviderInstallSpec, Mapping[str, str]], tuple[bool, str]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProviderSetupError(message)


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    _require(isinstance(value, dict), f"{field} must be an object")
    return value


def _require_string(value: Any, field: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{field} must be a non-empty string")
    return value


def _require_string_list(value: Any, field: str) -> tuple[str, ...]:
    _require(isinstance(value, list) and bool(value), f"{field} must be a non-empty list")
    _require(all(isinstance(item, str) and item for item in value), f"{field} must contain strings")
    _require(len(value) == len(set(value)), f"{field} must not contain duplicates")
    return tuple(value)


def _require_exact_keys(value: Mapping[str, Any], field: str, expected: set[str]) -> None:
    missing = expected - set(value)
    extra = set(value) - expected
    _require(not missing, f"{field} is missing fields: {', '.join(sorted(missing))}")
    _require(not extra, f"{field} has unknown fields: {', '.join(sorted(extra))}")


def _validate_https_url(value: Any, field: str) -> str:
    url = _require_string(value, field)
    parsed = urlparse(url)
    _require(parsed.scheme == "https", f"{field} must use https")
    _require(bool(parsed.hostname), f"{field} must include a host")
    _require(parsed.username is None and parsed.password is None, f"{field} must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProviderSetupError(f"{field} has an invalid port") from exc
    _require(port in {None, 443}, f"{field} must use the default HTTPS port")
    return url


def normalize_platform(system_name: str | None = None) -> str:
    """Return the manifest platform key for macOS, Linux, and WSL."""

    normalized = (system_name or platform.system()).strip().lower()
    if normalized == "darwin":
        return "darwin"
    if normalized == "linux":
        return "linux"
    raise ProviderSetupError(
        f"provider CLI setup is unsupported on {system_name or platform.system()!r}; "
        f"use macOS, Linux, or Windows through WSL; see {SETUP_DOCS_URL}"
    )


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProviderSetupError(f"cannot read {label} at {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProviderSetupError(
            f"{label} is malformed at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return _require_mapping(value, label)


def load_install_specs(
    repo_root: Path,
    *,
    system_name: str | None = None,
) -> tuple[ProviderInstallSpec, ...]:
    """Load and semantically validate provider installer recipes."""

    platform_id = normalize_platform(system_name)
    manifest = _load_json(repo_root / "config" / "provider-installers.json", "provider installer manifest")
    try:
        registry = load_registry(repo_root / "config" / "provider-registry.json")
    except RegistryError as exc:
        raise ProviderSetupError(f"provider registry is invalid: {exc}") from exc

    _require_exact_keys(manifest, "provider installer manifest", {"schemaVersion", "sourceVerifiedOn", "providers"})
    _require(manifest.get("schemaVersion") == 1, "provider installer manifest schemaVersion must be 1")
    verified_on = _require_string(manifest.get("sourceVerifiedOn"), "sourceVerifiedOn")
    try:
        date.fromisoformat(verified_on)
    except ValueError as exc:
        raise ProviderSetupError("sourceVerifiedOn must be an ISO date") from exc

    providers = _require_mapping(manifest.get("providers"), "providers")
    registry_providers = _require_mapping(registry.get("providers"), "provider registry providers")
    _require(
        set(providers) == set(registry_providers),
        "provider installer IDs must exactly match config/provider-registry.json",
    )

    specs: list[ProviderInstallSpec] = []
    for provider_id in registry_providers:
        raw_provider = providers[provider_id]
        provider = _require_mapping(raw_provider, f"providers.{provider_id}")
        _require_exact_keys(
            provider,
            f"providers.{provider_id}",
            {"documentationUrl", "platforms", "allowedRedirectHosts", "verifyArgs", "authArgs"},
        )
        registry_provider = _require_mapping(
            registry_providers[provider_id], f"provider registry providers.{provider_id}"
        )
        documentation_url = _validate_https_url(
            provider.get("documentationUrl"), f"providers.{provider_id}.documentationUrl"
        )
        platforms = _require_mapping(provider.get("platforms"), f"providers.{provider_id}.platforms")
        _require(
            set(platforms) == SUPPORTED_PLATFORMS,
            f"providers.{provider_id}.platforms must contain darwin and linux",
        )
        raw_recipe = _require_mapping(
            platforms.get(platform_id), f"providers.{provider_id}.platforms.{platform_id}"
        )
        _require_exact_keys(
            raw_recipe,
            f"providers.{provider_id}.platforms.{platform_id}",
            {"installerUrl", "interpreter", "sha256"},
        )
        installer_url = _validate_https_url(
            raw_recipe.get("installerUrl"),
            f"providers.{provider_id}.platforms.{platform_id}.installerUrl",
        )
        interpreter = _require_string_list(
            raw_recipe.get("interpreter"),
            f"providers.{provider_id}.platforms.{platform_id}.interpreter",
        )
        _require(
            interpreter[0] in ALLOWED_INTERPRETERS,
            f"providers.{provider_id} uses unsupported interpreter {interpreter[0]!r}",
        )
        _require(
            all(argument.startswith("-") for argument in interpreter[1:]),
            f"providers.{provider_id} interpreter arguments must be flags",
        )
        raw_sha256 = raw_recipe.get("sha256")
        _require(
            raw_sha256 is None
            or (
                isinstance(raw_sha256, str)
                and len(raw_sha256) == 64
                and all(character in "0123456789abcdef" for character in raw_sha256)
            ),
            f"providers.{provider_id}.platforms.{platform_id}.sha256 must be null or lowercase SHA-256",
        )
        allowed_hosts = _require_string_list(
            provider.get("allowedRedirectHosts"), f"providers.{provider_id}.allowedRedirectHosts"
        )
        _require(
            all(
                host == host.lower()
                and ".." not in host
                and all(part and not part.startswith("-") and not part.endswith("-") for part in host.split("."))
                and urlparse(f"https://{host}").hostname == host
                for host in allowed_hosts
            ),
            f"providers.{provider_id}.allowedRedirectHosts contains an invalid host",
        )
        initial_host = urlparse(installer_url).hostname
        _require(
            initial_host in allowed_hosts,
            f"providers.{provider_id} installer host must be in allowedRedirectHosts",
        )
        verify_args = _require_string_list(provider.get("verifyArgs"), f"providers.{provider_id}.verifyArgs")
        auth_args = _require_string_list(provider.get("authArgs"), f"providers.{provider_id}.authArgs")
        _require(
            all("key" not in item.lower() and "token" not in item.lower() for item in (*verify_args, *auth_args)),
            f"providers.{provider_id} verification/auth arguments must not name credentials",
        )
        override = registry_provider.get("binaryOverrideEnv")
        _require(
            override is None or isinstance(override, str),
            f"provider registry providers.{provider_id}.binaryOverrideEnv is invalid",
        )
        specs.append(
            ProviderInstallSpec(
                provider_id=provider_id,
                display_name=_require_string(
                    registry_provider.get("displayName"),
                    f"provider registry providers.{provider_id}.displayName",
                ),
                binary_override_env=override,
                documentation_url=documentation_url,
                recipe=PlatformRecipe(installer_url, interpreter, raw_sha256),
                allowed_redirect_hosts=frozenset(allowed_hosts),
                verify_args=verify_args,
                auth_args=auth_args,
            )
        )
    return tuple(specs)


def environment_with_user_bins(env: Mapping[str, str], home: Path) -> dict[str, str]:
    """Return an environment with existing common user install directories on PATH."""

    updated = dict(env)
    current = updated.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    existing = set(parts)
    additions: list[str] = []
    for relative in COMMON_USER_BIN_DIRS:
        candidate = str(home / relative)
        if candidate not in existing and Path(candidate).is_dir():
            additions.append(candidate)
            existing.add(candidate)
    updated["PATH"] = os.pathsep.join([*additions, *parts])
    return updated


def resolve_provider_binary(
    provider_id: str,
    env: Mapping[str, str],
    home: Path,
) -> str | None:
    """Resolve an adapter's candidate to an existing executable path."""

    candidate = get_adapter(provider_id).resolve_binary(env, home)
    if not candidate:
        return None
    expanded = os.path.expandvars(os.path.expanduser(candidate))
    if os.path.isabs(expanded) or os.sep in expanded:
        path = Path(expanded)
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    discovered = shutil.which(expanded, path=env.get("PATH"))
    return str(Path(discovered).resolve()) if discovered is not None else None


def detect_provider_rows(
    specs: Sequence[ProviderInstallSpec],
    env: Mapping[str, str],
) -> tuple[ProviderRow, ...]:
    home = Path(env.get("HOME", str(Path.home()))).expanduser()
    detection_env = environment_with_user_bins(env, home)
    return tuple(
        ProviderRow(
            provider_id=spec.provider_id,
            display_name=spec.display_name,
            installed_path=resolve_provider_binary(spec.provider_id, detection_env, home),
        )
        for spec in specs
    )


def initial_selection(rows: Sequence[ProviderRow]) -> SelectionState:
    cursor = next((index for index, row in enumerate(rows) if not row.installed), None)
    return SelectionState(tuple(rows), cursor)


def move_selection(state: SelectionState, offset: int) -> SelectionState:
    if state.cursor is None or not state.rows:
        return state
    index = state.cursor
    for _ in state.rows:
        index = (index + offset) % len(state.rows)
        if not state.rows[index].installed:
            return replace(state, cursor=index)
    return state


def toggle_selection(state: SelectionState) -> SelectionState:
    if state.cursor is None or state.rows[state.cursor].installed:
        return state
    provider_id = state.rows[state.cursor].provider_id
    selected = set(state.selected)
    if provider_id in selected:
        selected.remove(provider_id)
    else:
        selected.add(provider_id)
    return replace(state, selected=frozenset(selected))


def selected_provider_ids(state: SelectionState) -> tuple[str, ...]:
    return tuple(row.provider_id for row in state.rows if row.provider_id in state.selected)


def _signal_interrupt(signum: int, _frame: object) -> None:
    raise TerminalSignal(signum)


class TtySession:
    """A small `/dev/tty` cbreak session with deterministic restoration."""

    def __init__(self, path: str = "/dev/tty", *, term: str | None = None) -> None:
        self.path = path
        self.term = os.environ.get("TERM", "") if term is None else term
        self.fd: int | None = None
        self._attributes: list[Any] | None = None
        self._handlers: dict[int, Any] = {}
        self._painted_lines = 0

    @property
    def supports_cursor(self) -> bool:
        return self.term.lower() != "dumb"

    @property
    def descriptor(self) -> int:
        if self.fd is None:
            raise ProviderSetupError("terminal session is not open")
        return self.fd

    def __enter__(self) -> TtySession:
        if termios is None or tty is None:
            raise ProviderSetupError("provider CLI setup requires a Unix-compatible terminal")
        try:
            self.fd = os.open(self.path, os.O_RDWR | getattr(os, "O_NOCTTY", 0))
        except OSError as exc:
            raise ProviderSetupError(
                "provider CLI setup requires an interactive terminal; "
                "rerun it from macOS, Linux, or WSL"
            ) from exc
        if not os.isatty(self.fd):
            os.close(self.fd)
            self.fd = None
            raise ProviderSetupError("provider CLI setup terminal is not a TTY")
        try:
            self._attributes = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                self._handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, _signal_interrupt)
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        for signum, handler in self._handlers.items():
            signal.signal(signum, handler)
        self._handlers.clear()
        if self.fd is not None:
            if self.supports_cursor:
                try:
                    os.write(self.fd, b"\x1b[?25h")
                except OSError:
                    pass
            if self._attributes is not None and termios is not None:
                termios.tcsetattr(self.fd, termios.TCSANOW, self._attributes)
            os.close(self.fd)
            self.fd = None
        self._attributes = None

    def write(self, text: str) -> None:
        payload = text.encode("utf-8", errors="replace")
        view = memoryview(payload)
        while view:
            written = os.write(self.descriptor, view)
            view = view[written:]

    def read_key(self) -> str:
        first = os.read(self.descriptor, 1)
        if first == b"\x03":
            raise TerminalSignal(signal.SIGINT)
        if first != b"\x1b":
            return first.decode("utf-8", errors="ignore")
        suffix = bytearray()
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline and len(suffix) < 2:
            ready, _, _ = select.select([self.descriptor], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                break
            suffix.extend(os.read(self.descriptor, 1))
        if bytes(suffix) == b"[A":
            return "UP"
        if bytes(suffix) == b"[B":
            return "DOWN"
        return "ESC"

    def width(self) -> int:
        try:
            return max(24, os.get_terminal_size(self.descriptor).columns)
        except OSError:
            return 80

    def repaint(self, lines: Sequence[str]) -> None:
        cursor_hidden = self.supports_cursor
        try:
            if cursor_hidden:
                self.write("\x1b[?25l")
            if self.supports_cursor and self._painted_lines:
                self.write(f"\x1b[{self._painted_lines}F")
            elif self._painted_lines:
                self.write("\n")
            width = self.width()
            for line in lines:
                trimmed = line if len(line) <= width else line[: max(0, width - 3)] + "..."
                if self.supports_cursor:
                    self.write("\x1b[2K")
                self.write(trimmed + "\n")
            self._painted_lines = len(lines)
        finally:
            if cursor_hidden:
                self.write("\x1b[?25h")

    def finish_repaint(self) -> None:
        self.write("\n")
        self._painted_lines = 0

    def restore_input_mode(self) -> None:
        """Return the TTY to its original mode before an upstream installer runs."""

        if self.fd is not None and self._attributes is not None and termios is not None:
            termios.tcsetattr(self.fd, termios.TCSANOW, self._attributes)


def render_selection(state: SelectionState, *, use_color: bool) -> tuple[str, ...]:
    lines = [
        "Optional provider CLIs",
        "",
        "Select any missing CLIs you want to install.",
        "Use Up/Down to move, Space to toggle, Enter to continue, q to skip.",
        "",
    ]
    for index, row in enumerate(state.rows):
        focused = index == state.cursor
        marker = "x" if row.installed or row.provider_id in state.selected else " "
        detail = f"installed: {row.installed_path}" if row.installed else "not found"
        line = f"{'>' if focused else ' '} [{marker}] {row.display_name:<20} {detail}"
        if focused and use_color:
            line = f"\x1b[7m{line}\x1b[0m"
        lines.append(line)
    installed = sum(row.installed for row in state.rows)
    available = len(state.rows) - installed
    lines.extend(["", f"{installed} installed, {available} available to install"])
    return tuple(lines)


def choose_providers(
    rows: Sequence[ProviderRow],
    session: TtySession,
    *,
    no_color: bool,
) -> tuple[str, ...] | None:
    """Render the selector and return selected IDs, or ``None`` for explicit skip."""

    state = initial_selection(rows)
    use_color = not no_color and "NO_COLOR" not in os.environ and session.term.lower() != "dumb"
    while True:
        session.repaint(render_selection(state, use_color=use_color))
        key = session.read_key()
        if key in {"UP", "k", "K"}:
            state = move_selection(state, -1)
        elif key in {"DOWN", "j", "J"}:
            state = move_selection(state, 1)
        elif key == " ":
            state = toggle_selection(state)
        elif key in {"\r", "\n"}:
            session.finish_repaint()
            return selected_provider_ids(state)
        elif key in {"q", "Q", "ESC"}:
            session.finish_repaint()
            return None


def confirm_selection(
    selected: Sequence[ProviderInstallSpec],
    session: TtySession,
    *,
    dry_run: bool,
) -> bool:
    action = "Preview" if dry_run else "Install"
    session.write(f"{action} these provider CLIs?\n\n")
    for spec in selected:
        host = urlparse(spec.recipe.installer_url).hostname or "unknown host"
        checksum = (
            f"SHA-256 {spec.recipe.sha256[:12]}… pinned"
            if spec.recipe.sha256 is not None
            else "WARNING: no pinned checksum"
        )
        session.write(f"  - {spec.display_name} — official installer from {host}; {checksum}\n")
    if dry_run:
        session.write("\nDry-run mode will not download or execute anything.\n")
    else:
        session.write(
            "\nThe installers download software and may update user-level PATH configuration.\n"
            "No login or provider configuration will be performed.\n"
        )
    session.write("\nContinue? [y/N] ")
    while True:
        key = session.read_key()
        if key in {"y", "Y"}:
            session.write("y\n\n")
            return True
        if key in {"n", "N", "q", "Q", "ESC", "\r", "\n"}:
            session.write("no\n")
            return False


def download_installer(spec: ProviderInstallSpec) -> InstallerDownload:
    """Download and validate a bounded first-party installer in memory."""

    request = Request(spec.recipe.installer_url, headers={"User-Agent": USER_AGENT})
    started = time.monotonic()
    try:
        opener = build_opener(ApprovedRedirectHandler(spec.allowed_redirect_hosts))
        response = opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        with response:
            status = getattr(response, "status", 200)
            if status is not None and not 200 <= int(status) < 300:
                raise InstallerDownloadError(f"installer download returned HTTP {status}")
            effective_url = response.geturl()
            parsed = urlparse(effective_url)
            if parsed.scheme != "https" or parsed.hostname not in spec.allowed_redirect_hosts:
                raise InstallerDownloadError(
                    f"installer redirected to unapproved host {parsed.hostname or '<missing>'}"
                )
            content = bytearray()
            while len(content) <= MAX_INSTALLER_BYTES:
                if time.monotonic() - started > DOWNLOAD_TOTAL_SECONDS:
                    raise InstallerDownloadError("installer download exceeded the time limit")
                chunk = response.read(min(64 * 1024, MAX_INSTALLER_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
    except InstallerDownloadError:
        raise
    except (HTTPError, URLError, HTTPException, OSError, TimeoutError) as exc:
        raise InstallerDownloadError(f"installer download failed: {exc}") from exc
    if not content:
        raise InstallerDownloadError("installer download was empty")
    if len(content) > MAX_INSTALLER_BYTES:
        raise InstallerDownloadError(
            f"installer exceeded the {MAX_INSTALLER_BYTES}-byte size limit"
        )
    if not content.startswith(b"#!"):
        raise InstallerDownloadError("installer does not begin with a script shebang")
    payload = bytes(content)
    digest = hashlib.sha256(payload).hexdigest()
    if spec.recipe.sha256 is not None and not hmac.compare_digest(digest, spec.recipe.sha256):
        raise InstallerDownloadError(
            "installer SHA-256 did not match the reviewed manifest; "
            "the upstream script may have changed"
        )
    safe_effective_url = parsed._replace(params="", query="", fragment="").geturl()
    return InstallerDownload(payload, safe_effective_url, digest)


def run_installer(argv: Sequence[str], env: Mapping[str, str], terminal_fd: int) -> int:
    """Run an installer as an argv array while streaming through the user's TTY."""

    process = subprocess.Popen(
        list(argv),
        stdin=terminal_fd,
        stdout=terminal_fd,
        stderr=terminal_fd,
        env=dict(env),
        start_new_session=True,
    )
    try:
        return process.wait(timeout=INSTALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_installer(process)
        return 124
    except BaseException:
        _terminate_installer(process)
        raise


def _terminate_installer(process: subprocess.Popen[bytes]) -> None:
    """Bound shutdown of an installer process group without masking an interruption."""

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=2)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


def verify_installed_binary(
    binary: str,
    spec: ProviderInstallSpec,
    env: Mapping[str, str],
) -> tuple[bool, str]:
    try:
        result = run_bounded_capture(
            [binary, *spec.verify_args],
            env=env,
            timeout_seconds=VERIFY_TIMEOUT_SECONDS,
            max_bytes=VERIFY_MAX_BYTES,
        )
    except OSError as exc:
        return False, f"version verification could not start: {exc}"
    if result.timed_out:
        return False, "version verification timed out"
    if result.returncode != 0:
        return False, f"version verification exited {result.returncode}"
    output = (result.stdout or result.stderr).decode("utf-8", errors="replace")
    version = " ".join(output.split())[:200]
    return True, (
        f"local version command succeeded: {version}"
        if version
        else "local version command succeeded"
    )


def install_selected(
    selected: Sequence[ProviderInstallSpec],
    env: Mapping[str, str],
    terminal_fd: int,
    *,
    dry_run: bool = False,
    downloader: DownloadFunction = download_installer,
    installer_runner: InstallerRunner = run_installer,
    verifier: Verifier = verify_installed_binary,
) -> tuple[InstallResult, ...]:
    """Install selected missing providers independently and return stable results."""

    home = Path(env.get("HOME", str(Path.home()))).expanduser()
    results: list[InstallResult] = []
    for spec in selected:
        current_env = environment_with_user_bins(env, home)
        existing = resolve_provider_binary(spec.provider_id, current_env, home)
        if existing:
            results.append(
                InstallResult(spec.provider_id, "already-installed", "already installed", existing)
            )
            continue
        if dry_run:
            argv = [*spec.recipe.interpreter, "<downloaded-installer>"]
            results.append(
                InstallResult(
                    spec.provider_id,
                    "dry-run",
                    f"would download {spec.recipe.installer_url} and run {' '.join(argv)}",
                )
            )
            continue

        temporary_path: Path | None = None
        try:
            downloaded = downloader(spec)
            if isinstance(downloaded, InstallerDownload):
                content = downloaded.content
                source_note = (
                    f"source {downloaded.resolved_url}; installer sha256 {downloaded.sha256}"
                )
            else:
                content = downloaded
                source_note = "installer source supplied by caller"
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f"model-routing-{spec.provider_id}-",
                suffix=".sh",
            )
            temporary_path = Path(raw_path)
            try:
                os.fchmod(descriptor, 0o600)
                stream = os.fdopen(descriptor, "wb")
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            with stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            returncode = installer_runner(
                [*spec.recipe.interpreter, str(temporary_path)],
                current_env,
                terminal_fd,
            )
            if returncode != 0:
                results.append(
                    InstallResult(
                        spec.provider_id,
                        "failed",
                        (
                            "installer timed out" if returncode == 124 else f"installer exited {returncode}"
                        )
                        + f"; {source_note}",
                    )
                )
                continue
            refreshed_env = environment_with_user_bins(env, home)
            resolved = resolve_provider_binary(spec.provider_id, refreshed_env, home)
            if not resolved:
                results.append(
                    InstallResult(
                        spec.provider_id,
                        "failed",
                        "installer exited successfully but the binary is still unresolved; "
                        f"restart the shell or fix PATH; {source_note}",
                    )
                )
                continue
            verified, message = verifier(resolved, spec, refreshed_env)
            if not verified:
                results.append(
                    InstallResult(spec.provider_id, "failed", f"{message}; {source_note}", resolved)
                )
                continue
            results.append(
                InstallResult(spec.provider_id, "installed", f"{message}; {source_note}", resolved)
            )
        except InstallerDownloadError as exc:
            results.append(
                InstallResult(
                    spec.provider_id,
                    "failed",
                    f"{exc}; see {spec.documentation_url}",
                )
            )
        except OSError as exc:
            results.append(InstallResult(spec.provider_id, "failed", f"local installer failure: {exc}"))
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
    return tuple(results)


def render_setup_summary(
    rows: Sequence[ProviderRow],
    specs: Sequence[ProviderInstallSpec],
    results: Sequence[InstallResult],
) -> str:
    by_result = {result.provider_id: result for result in results}
    by_spec = {spec.provider_id: spec for spec in specs}
    lines = ["Provider setup summary", ""]
    installed_ids: set[str] = set()
    for row in rows:
        result = by_result.get(row.provider_id)
        if result is not None:
            detail = result.message
            if result.resolved_binary:
                detail = f"{detail}: {result.resolved_binary}"
            lines.append(f"  {row.display_name:<22} {result.status}: {detail}")
            if result.status in {"installed", "already-installed"}:
                installed_ids.add(row.provider_id)
        elif row.installed:
            lines.append(f"  {row.display_name:<22} already installed: {row.installed_path}")
            installed_ids.add(row.provider_id)
        else:
            lines.append(f"  {row.display_name:<22} not selected")
    lines.extend(["", "No authentication was performed."])
    if installed_ids:
        lines.append("Authenticate installed providers when ready:")
        for provider_id in (spec.provider_id for spec in specs if spec.provider_id in installed_ids):
            spec = by_spec[provider_id]
            lines.append(f"  {provider_id} {' '.join(spec.auth_args)}")
    lines.append("Run `model-routing doctor` to verify the completed setup.")
    return "\n".join(lines) + "\n"


def run_provider_setup(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    dry_run: bool = False,
    no_color: bool = False,
    tty_path: str = "/dev/tty",
    output: TextIO | None = None,
    downloader: DownloadFunction = download_installer,
    installer_runner: InstallerRunner = run_installer,
    verifier: Verifier = verify_installed_binary,
) -> int:
    """Run the complete provider selector.  Returns the documented CLI exit code."""

    destination = output
    if destination is None:
        import sys

        destination = sys.stdout
    specs = load_install_specs(repo_root)
    rows = detect_provider_rows(specs, env)
    if all(row.installed for row in rows):
        print("All five provider CLIs are already detected; nothing to install.", file=destination)
        return 0

    try:
        with TtySession(tty_path, term=env.get("TERM")) as session:
            selected_ids = choose_providers(
                rows,
                session,
                no_color=no_color or "NO_COLOR" in env,
            )
            if selected_ids is None:
                session.write("Provider CLI setup skipped.\n")
                return 0
            if not selected_ids:
                session.write("No provider CLIs selected.\n")
                return 0
            spec_by_id = {spec.provider_id: spec for spec in specs}
            selected = tuple(spec_by_id[provider_id] for provider_id in selected_ids)
            if not confirm_selection(selected, session, dry_run=dry_run):
                session.write("Provider CLI setup cancelled; nothing was installed.\n")
                return 0
            session.restore_input_mode()
            results = install_selected(
                selected,
                env,
                session.descriptor,
                dry_run=dry_run,
                downloader=downloader,
                installer_runner=installer_runner,
                verifier=verifier,
            )
            session.write("\n" + render_setup_summary(rows, specs, results))
            return 1 if any(result.status == "failed" for result in results) else 0
    except TerminalSignal as exc:
        return 128 + exc.signum


__all__ = [
    "InstallResult",
    "InstallerDownload",
    "InstallerDownloadError",
    "PlatformRecipe",
    "ProviderInstallSpec",
    "ProviderRow",
    "ProviderSetupError",
    "SelectionState",
    "TtySession",
    "choose_providers",
    "confirm_selection",
    "detect_provider_rows",
    "download_installer",
    "environment_with_user_bins",
    "initial_selection",
    "install_selected",
    "load_install_specs",
    "move_selection",
    "normalize_platform",
    "render_selection",
    "render_setup_summary",
    "resolve_provider_binary",
    "run_provider_setup",
    "selected_provider_ids",
    "toggle_selection",
]
