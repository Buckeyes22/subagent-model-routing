"""Deterministic preflight doctor for the subagent-model-routing runtime.

The default doctor validates only what the local, read-only environment can
prove. Model discovery is available solely through an explicit mode, never
mutates provider authentication or configuration, and degrades to warnings
when provider output changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Callable, Iterable, Mapping
import subprocess

from .registry import RegistryError, validate_registry
from .run_store import config_root, state_root
from .providers import adapter_ids, get_adapter
from .discovery import discover_models as run_model_discovery


SCHEMA_VERSION = 1
VALID_STATUSES = ("PASS", "WARN", "FAIL", "SKIP")
RUNTIME_CATEGORY = "runtime"
PROVIDER_CATEGORY = "provider"
PLUGIN_CATEGORY = "plugin"
SECURITY_CATEGORY = "security"

DRIFT_FRAGMENTS = (
    "registry and adapter implementations must match",
    "registry and adapter disagree",
)

DEFAULT_VERSION_TIMEOUT = 5.0
DEFAULT_HELP_TIMEOUT = 5.0
DEFAULT_OVERSIZED_STATE_BYTES = 200 * 1024 * 1024
DEFAULT_WORKTREE_BACKLOG_COUNT = 25
GIT_MIN_VERSION = (2, 20)
WORLD_BITS = 0o077

PROVIDER_HELP: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "codex": (("exec", "--help"), ("exec", "--skip-git-repo-check")),
    "claude": (("--help",), ("--no-session-persistence", "--output-format")),
    "grok": (("--help",), ("--no-auto-update", "--output-format")),
    "kimi": (("--help",), ("--prompt", "--output-format", "doctor", "provider")),
    "opencode": (("run", "--help"), ("--format",)),
}


@dataclass(slots=True, frozen=True)
class DoctorCheck:
    id: str
    category: str
    status: str
    summary: str
    remediation: str | None = None
    provider: str | None = None
    details: Mapping[str, Any] | None = None


@dataclass(slots=True)
class DoctorReport:
    schema_version: int = SCHEMA_VERSION
    tool: str = "subagent-model-routing doctor"
    generated_at: str = ""
    modes: dict[str, Any] = field(default_factory=dict)
    status: str = "pass"
    summary: dict[str, int] = field(default_factory=lambda: {"pass": 0, "warn": 0, "fail": 0, "skip": 0})
    checks: list[DoctorCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schemaVersion": self.schema_version,
            "tool": self.tool,
            "generatedAt": self.generated_at,
            "modes": dict(self.modes),
            "status": self.status,
            "summary": dict(self.summary),
            "checks": [_check_to_dict(check) for check in self.checks],
        }
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def _check_to_dict(check: DoctorCheck) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": check.id,
        "category": check.category,
        "status": check.status,
        "summary": check.summary,
    }
    if check.remediation is not None:
        payload["remediation"] = check.remediation
    if check.provider is not None:
        payload["provider"] = check.provider
    if check.details:
        payload["details"] = _freeze_details(check.details)
    return payload


def _freeze_details(details: Mapping[str, Any]) -> Any:
    if isinstance(details, Mapping):
        return {str(key): _freeze_details(value) for key, value in details.items()}
    if isinstance(details, (list, tuple)):
        return [_freeze_details(item) for item in details]
    if isinstance(details, (str, int, float, bool)) or details is None:
        return details
    return repr(details)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _resolve_provider_filter(
    requested: str | None,
    *,
    available_providers: Iterable[str],
) -> str | None:
    if requested is None:
        return None
    if requested not in set(available_providers):
        raise ValueError(f"unknown provider filter: {requested!r}")
    return requested


def _status_from_counts(counts: Mapping[str, int]) -> str:
    if counts.get("fail", 0) > 0:
        return "fail"
    if counts.get("warn", 0) > 0:
        return "warn"
    return "pass"


def _is_drift_error(message: str) -> bool:
    return any(fragment in message for fragment in DRIFT_FRAGMENTS)


def _read_registry(repo_root: Path) -> tuple[dict[str, Any] | None, DoctorCheck | None]:
    path = repo_root / "config" / "provider-registry.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, DoctorCheck(
            id="runtime.registry_present",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary=f"cannot read provider registry at {path}: {exc}",
            remediation=f"restore config/provider-registry.json or run from a valid checkout: {path}",
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, DoctorCheck(
            id="runtime.registry_present",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary=f"provider registry JSON is malformed: {exc.msg} (line {exc.lineno}, column {exc.colno})",
            remediation=f"repair {path} so it parses as valid JSON; compare with the upstream checkout if unsure",
        )
    try:
        validate_registry(data, repo_root=repo_root)
    except RegistryError as exc:
        return None, _classify_registry_error(exc, path=path)
    return data, None


def _classify_registry_error(exc: RegistryError, *, path: Path) -> DoctorCheck:
    message = str(exc)
    if _is_drift_error(message):
        return DoctorCheck(
            id="runtime.registry_drift",
            category=RUNTIME_CATEGORY,
            status="WARN",
            summary=f"provider registry/adapter drift detected: {message}",
            remediation=(
                "reconcile config/provider-registry.json with the adapters in runtime/model_routing/providers/ "
                f"so they describe the same providers, promptDelivery, and binaryOverrideEnv ({path})"
            ),
            details={"error": message, "path": str(path)},
        )
    return DoctorCheck(
        id="runtime.registry_valid",
        category=RUNTIME_CATEGORY,
        status="FAIL",
        summary=f"provider registry is invalid: {message}",
        remediation=(
            f"run `python3 tools/validate_registry.py` to inspect {path}, fix the flagged field, "
            "and run `python3 tools/sync_routes.py` if the regenerated hosts need updating"
        ),
        details={"error": message, "path": str(path)},
    )


def _check_python_version(repo_root: Path, env: Mapping[str, str]) -> DoctorCheck:

    info = sys.version_info
    version = f"{info.major}.{info.minor}.{info.micro}"
    if (info.major, info.minor) >= (3, 11):
        return DoctorCheck(
            id="runtime.python",
            category=RUNTIME_CATEGORY,
            status="PASS",
            summary=f"Python {version} meets the 3.11+ requirement",
            details={"version": version},
        )
    return DoctorCheck(
        id="runtime.python",
        category=RUNTIME_CATEGORY,
        status="FAIL",
        summary=f"Python {version} is too old (>=3.11 required)",
        remediation=(
            "install Python 3.11 or newer (for example via Homebrew, deadsnakes, or pyenv) "
            "and rerun model-routing doctor"
        ),
        details={"version": version},
    )


def _check_git(repo_root: Path, env: Mapping[str, str]) -> DoctorCheck:
    path_dir = env.get("PATH")
    binary = shutil.which("git", path=path_dir)
    if not binary:
        return DoctorCheck(
            id="runtime.git",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary="git executable not found on PATH",
            remediation="install git (https://git-scm.com/downloads) and rerun model-routing doctor",
        )
    try:
        result = subprocess.run(
            [binary, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DoctorCheck(
            id="runtime.git",
            category=RUNTIME_CATEGORY,
            status="WARN",
            summary=f"could not invoke git --version: {exc}",
            remediation="verify the git installation is functional before relying on isolated-worktree dispatch",
            details={"binary": binary},
        )
    output = result.stdout.decode("utf-8", errors="replace") or result.stderr.decode("utf-8", errors="replace")
    match = re.search(r"git version (\d+)\.(\d+)", output)
    version = f"{match.group(1)}.{match.group(2)}" if match else output.strip().splitlines()[0] if output else "unknown"
    if match and (int(match.group(1)), int(match.group(2))) >= GIT_MIN_VERSION:
        return DoctorCheck(
            id="runtime.git",
            category=RUNTIME_CATEGORY,
            status="PASS",
            summary=f"git {version} available via {binary}",
            details={"binary": binary, "version": version},
        )
    return DoctorCheck(
        id="runtime.git",
        category=RUNTIME_CATEGORY,
        status="WARN",
        summary=f"git {version} available but {GIT_MIN_VERSION[0]}.{GIT_MIN_VERSION[1]}+ recommended",
        remediation=f"upgrade git to {GIT_MIN_VERSION[0]}.{GIT_MIN_VERSION[1]} or newer for reliable isolated-worktree dispatch",
        details={"binary": binary, "version": version},
    )


def _check_state_dir(repo_root: Path, env: Mapping[str, str]) -> DoctorCheck:
    root = state_root(env)
    existing = root
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir() or not os.access(existing, os.W_OK | os.X_OK):
        return DoctorCheck(
            id="runtime.state_dir_writable",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary=f"state directory cannot be created or written through {existing}",
            remediation=(
                "ensure the parent directory exists and is writable by the current user "
                f"(nearest existing parent={existing}); set SUBAGENT_MODEL_ROUTING_STATE_HOME to a writable path if needed"
            ),
            details={"path": str(root)},
        )
    try:
        if root.exists() and root.stat().st_mode & WORLD_BITS:
            return DoctorCheck(
                id="runtime.state_dir_writable",
                category=RUNTIME_CATEGORY,
                status="WARN",
                summary=f"state directory is readable by other users: {root}",
                remediation=f"chmod 700 {root} so dispatch artifacts stay private",
                details={"path": str(root), "mode": oct(root.stat().st_mode & 0o777)},
            )
    except OSError:
        pass
    return DoctorCheck(
        id="runtime.state_dir_writable",
        category=RUNTIME_CATEGORY,
        status="PASS",
        summary=f"state directory is writable or creatable at {root}",
        details={"path": str(root)},
    )


def _check_ledger_parent(repo_root: Path, env: Mapping[str, str]) -> DoctorCheck:
    if env.get("SUBAGENT_MODEL_ROUTING_LEDGER"):
        target = Path(env["SUBAGENT_MODEL_ROUTING_LEDGER"]).expanduser()
    else:
        home = Path(env.get("HOME", "~")).expanduser()
        target = home / ".claude" / "subagent-model-routing" / "ledger" / "observations.jsonl"
    parent = target.parent
    existing = parent
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir() or not os.access(existing, os.W_OK | os.X_OK):
        return DoctorCheck(
            id="runtime.ledger_parent_writable",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary=f"ledger parent directory cannot be created or written through {existing}",
            remediation=(
                "ensure the ledger parent directory exists and is writable; "
                "override SUBAGENT_MODEL_ROUTING_LEDGER to a writable path if the default location is blocked"
            ),
            details={"path": str(parent)},
        )
    return DoctorCheck(
        id="runtime.ledger_parent_writable",
        category=RUNTIME_CATEGORY,
        status="PASS",
        summary=f"ledger parent directory is writable or creatable at {parent}",
        details={"path": str(parent)},
    )


def _check_generated_routes(repo_root: Path, env: Mapping[str, str], registry: Mapping[str, Any]) -> DoctorCheck:
    try:
        from tools.sync_routes import generated_files as generate
    except ImportError:
        sys_path = str(repo_root)
        if sys_path not in __import__("sys").path:
            __import__("sys").path.insert(0, sys_path)
        from tools.sync_routes import generated_files as generate
    generated = generate(dict(registry))
    mismatches: list[dict[str, str]] = []
    for path, expected in generated.items():
        if not path.is_file():
            mismatches.append({"path": str(path), "issue": "missing"})
            continue
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError as exc:
            mismatches.append({"path": str(path), "issue": f"unreadable: {exc}"})
            continue
        if actual != expected:
            mismatches.append({"path": str(path), "issue": "content mismatch"})
    if mismatches:
        return DoctorCheck(
            id="runtime.generated_routes",
            category=RUNTIME_CATEGORY,
            status="WARN",
            summary=f"{len(mismatches)} generated route file(s) are out of sync with the registry",
            remediation="run `python3 tools/sync_routes.py` to refresh the generated host-specific route assets",
            details={"mismatches": mismatches},
        )
    return DoctorCheck(
        id="runtime.generated_routes",
        category=RUNTIME_CATEGORY,
        status="PASS",
        summary=f"{len(generated)} generated route file(s) match the registry",
        details={"files": len(generated)},
    )


def _check_install_links(repo_root: Path, env: Mapping[str, str]) -> DoctorCheck:
    scripts = Path(env["SUBAGENT_MODEL_ROUTING_INSTALL_DIR"]).expanduser() if env.get("SUBAGENT_MODEL_ROUTING_INSTALL_DIR") else repo_root / "scripts"
    required = (
        "model-routing",
        "codex-shim.sh",
        "claude-shim.sh",
        "grok-shim.sh",
        "kimi-shim.sh",
        "opencode-shim.sh",
    )
    if not scripts.is_dir():
        return DoctorCheck(
            id="runtime.install_links",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary=f"scripts directory missing at {scripts}",
            remediation=f"verify the checkout is intact; restore {scripts} from the upstream repository if necessary",
        )
    missing: list[str] = []
    not_executable: list[str] = []
    for name in required:
        target = scripts / name
        if not target.exists():
            missing.append(name)
            continue
        if not os.access(target, os.X_OK):
            not_executable.append(name)
    if missing or not_executable:
        return DoctorCheck(
            id="runtime.install_links",
            category=RUNTIME_CATEGORY,
            status="WARN",
            summary="install entrypoints are not all present or executable",
            remediation=(
                "restore the missing files or run `chmod +x` on the affected scripts; "
                "rerun `scripts/install.sh` to repopulate `~/.claude/scripts/` symlinks"
            ),
            details={"missing": missing, "not_executable": not_executable},
        )
    return DoctorCheck(
        id="runtime.install_links",
        category=RUNTIME_CATEGORY,
        status="PASS",
        summary=f"all {len(required)} install entrypoints are present and executable in {scripts}",
    )


def _check_hooks_config(repo_root: Path, env: Mapping[str, str]) -> DoctorCheck:
    path = config_root(env) / "hooks.json"
    if not path.exists():
        return DoctorCheck(
            id="runtime.hooks_config",
            category=RUNTIME_CATEGORY,
            status="SKIP",
            summary=f"no portable hooks.json configured at {path}",
            remediation=(
                f"create {path} with an empty object (`{{}}`) if you want portable dispatch lifecycle hooks; "
                "see docs/lifecycle-hooks.md"
            ),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return DoctorCheck(
            id="runtime.hooks_config",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary=f"hooks.json is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})",
            remediation=f"repair or remove {path}; hooks are fail-open but malformed JSON disables them",
            details={"path": str(path)},
        )
    if not isinstance(data, dict):
        return DoctorCheck(
            id="runtime.hooks_config",
            category=RUNTIME_CATEGORY,
            status="FAIL",
            summary="hooks.json must be an object mapping event names to hook definitions",
            remediation=f"rewrite {path} as a JSON object (see examples/lifecycle-hooks.json)",
            details={"path": str(path)},
        )
    return DoctorCheck(
        id="runtime.hooks_config",
        category=RUNTIME_CATEGORY,
        status="PASS",
        summary=f"hooks.json at {path} parses cleanly ({len(data)} event(s))",
        details={"events": sorted(data)},
    )


def _check_provider_binary_resolved(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
) -> DoctorCheck:
    home = Path(env.get("HOME", "~")).expanduser()
    adapter = get_adapter(provider_id)
    binary = adapter.resolve_binary(env, home)
    resolved = None if binary is None else binary if os.path.isabs(binary) and os.path.isfile(binary) else shutil.which(binary, path=env.get("PATH"))
    if resolved:
        return DoctorCheck(
            id=f"provider.{provider_id}.binary_resolved",
            category=PROVIDER_CATEGORY,
            status="PASS",
            summary=f"{provider_id} binary resolves to {resolved}",
            provider=provider_id,
            details={"binary": resolved},
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.binary_resolved",
        category=PROVIDER_CATEGORY,
        status="WARN",
        summary=f"{provider_id} executable is not on PATH and no override is set",
        remediation=(
            f"install the {provider_id} CLI or set {adapter.binary_override_env or 'BIN_OVERRIDE'} "
            "to a valid executable path before dispatching work"
        ),
        provider=provider_id,
    )


def _check_provider_executable_bit(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    home = Path(env.get("HOME", "~")).expanduser()
    adapter = get_adapter(provider_id)
    binary = adapter.resolve_binary(env, home)
    if binary is None:
        return DoctorCheck(
            id=f"provider.{provider_id}.executable_bit",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"cannot check executable bit for {provider_id}: binary unresolved",
            provider=provider_id,
        )
    resolved = binary if os.path.isabs(binary) else shutil.which(binary, path=env.get("PATH"))
    if resolved is None or not os.path.isfile(resolved):
        return DoctorCheck(
            id=f"provider.{provider_id}.executable_bit",
            category=PROVIDER_CATEGORY,
            status="WARN",
            summary=f"{provider_id} binary does not resolve to a file: {binary}",
            remediation=(
                f"set {adapter.binary_override_env or 'BIN_OVERRIDE'} to an existing executable, "
                "or unset it to fall back to PATH lookup"
            ),
            provider=provider_id,
            details={"binary": binary},
        )
    if os.access(resolved, os.X_OK):
        return DoctorCheck(
            id=f"provider.{provider_id}.executable_bit",
            category=PROVIDER_CATEGORY,
            status="PASS",
            summary=f"{provider_id} binary at {resolved} has the executable bit set",
            provider=provider_id,
            details={"binary": resolved},
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.executable_bit",
        category=PROVIDER_CATEGORY,
        status="WARN",
        summary=f"{provider_id} binary at {resolved} is not executable",
        remediation=f"run `chmod +x {resolved}` or restore a real executable at that path",
        provider=provider_id,
        details={"binary": resolved},
    )


def _check_provider_cli_contract(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
) -> DoctorCheck:
    """Inspect only local help/version surfaces; never query models or auth."""
    home = Path(env.get("HOME", "~")).expanduser()
    binary = get_adapter(provider_id).resolve_binary(env, home)
    if binary is None:
        return DoctorCheck(
            id=f"provider.{provider_id}.cli_contract",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"cannot inspect {provider_id} help/version because its binary is unresolved",
            provider=provider_id,
        )
    help_args, required = PROVIDER_HELP[provider_id]
    child_env = dict(env)
    child_env.update({"NO_COLOR": "1", "GIT_TERMINAL_PROMPT": "0"})
    outputs: dict[str, str] = {}
    for label, arguments in (("version", ("--version",)), ("help", help_args)):
        try:
            result = subprocess.run(
                [binary, *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                timeout=DEFAULT_HELP_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DoctorCheck(
                id=f"provider.{provider_id}.cli_contract",
                category=PROVIDER_CATEGORY,
                status="WARN",
                summary=f"{provider_id} local {label} inspection failed: {exc}",
                remediation=f"run `{binary} {' '.join(arguments)}` and verify the installed CLI",
                provider=provider_id,
            )
        outputs[label] = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if result.returncode != 0:
            return DoctorCheck(
                id=f"provider.{provider_id}.cli_contract",
                category=PROVIDER_CATEGORY,
                status="WARN",
                summary=f"{provider_id} local {label} command exited {result.returncode}",
                remediation=f"run `{binary} {' '.join(arguments)}` and verify the installed CLI",
                provider=provider_id,
                details={"exitCode": result.returncode},
            )
    missing = [fragment for fragment in required if fragment not in outputs["help"]]
    if missing:
        return DoctorCheck(
            id=f"provider.{provider_id}.cli_contract",
            category=PROVIDER_CATEGORY,
            status="WARN",
            summary=f"{provider_id} help output is missing expected flag(s): {', '.join(missing)}",
            remediation="upgrade the provider CLI or compare its current help with the adapter arguments before dispatching",
            provider=provider_id,
            details={"version": outputs["version"].strip()[:256], "missing": missing},
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.cli_contract",
        category=PROVIDER_CATEGORY,
        status="PASS",
        summary=f"{provider_id} local version/help contract is available",
        provider=provider_id,
        details={"version": outputs["version"].strip()[:256]},
    )


def _check_provider_binary_override(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    adapter = get_adapter(provider_id)
    override_env = adapter.binary_override_env
    if not override_env:
        return DoctorCheck(
            id=f"provider.{provider_id}.binary_override_env",
            category=PROVIDER_CATEGORY,
            status="PASS",
            summary=f"{provider_id} does not declare a binary override environment variable",
            provider=provider_id,
        )
    if env.get(override_env):
        return DoctorCheck(
            id=f"provider.{provider_id}.binary_override_env",
            category=PROVIDER_CATEGORY,
            status="PASS",
            summary=f"{override_env} is set for {provider_id}",
            provider=provider_id,
            details={"overrideEnv": override_env, "value": env[override_env]},
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.binary_override_env",
        category=PROVIDER_CATEGORY,
        status="SKIP",
        summary=f"{override_env} is unset for {provider_id}",
        provider=provider_id,
        details={"overrideEnv": override_env},
    )


def _check_provider_default_model(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    provider = registry["providers"][provider_id]
    default = provider.get("defaultModel", {})
    source = default.get("source")
    fallback = default.get("fallback")
    models = provider.get("models", {})
    if source == "registry":
        if fallback in models:
            return DoctorCheck(
                id=f"provider.{provider_id}.default_model",
                category=PROVIDER_CATEGORY,
                status="PASS",
                summary=f"{provider_id} default model {fallback!r} is a known registry model",
                provider=provider_id,
                details={"defaultModel": fallback},
            )
        if provider.get("allowUnknownModels"):
            return DoctorCheck(
                id=f"provider.{provider_id}.default_model",
                category=PROVIDER_CATEGORY,
                status="WARN",
                summary=f"{provider_id} default model {fallback!r} is not present in the registry models map",
                remediation=(
                    f"register {fallback!r} under providers.{provider_id}.models or pick a different fallback "
                    "so the registry/contract is closed-loop"
                ),
                provider=provider_id,
                details={"defaultModel": fallback},
            )
        return DoctorCheck(
            id=f"provider.{provider_id}.default_model",
            category=PROVIDER_CATEGORY,
            status="WARN",
            summary=f"{provider_id} default model {fallback!r} is unknown and the provider does not allow unknown models",
            remediation=(
                f"add {fallback!r} to providers.{provider_id}.models in config/provider-registry.json, "
                "or set allowUnknownModels=true to preserve pass-through"
            ),
            provider=provider_id,
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.default_model",
        category=PROVIDER_CATEGORY,
        status="PASS",
        summary=f"{provider_id} default model source is {source!r}",
        provider=provider_id,
        details={"source": source, "fallback": fallback},
    )


def _check_provider_contract_drift(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    adapter = get_adapter(provider_id)
    provider = registry["providers"][provider_id]
    drift: list[str] = []
    expected_delivery = provider.get("promptDelivery")
    if adapter.prompt_delivery != expected_delivery:
        drift.append(
            f"promptDelivery: adapter={adapter.prompt_delivery!r}, registry={expected_delivery!r}"
        )
    expected_override = provider.get("binaryOverrideEnv")
    if adapter.binary_override_env != expected_override:
        drift.append(
            f"binaryOverrideEnv: adapter={adapter.binary_override_env!r}, registry={expected_override!r}"
        )
    if drift:
        return DoctorCheck(
            id=f"provider.{provider_id}.contract_drift",
            category=PROVIDER_CATEGORY,
            status="WARN",
            summary=f"{provider_id} adapter and registry disagree about contract fields",
            remediation=(
                f"update runtime/model_routing/providers/{provider_id}.py (provider_id, prompt_delivery, "
                "binary_override_env) or the matching config/provider-registry.json entry so they describe the same contract"
            ),
            provider=provider_id,
            details={"drift": drift},
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.contract_drift",
        category=PROVIDER_CATEGORY,
        status="PASS",
        summary=f"{provider_id} adapter matches registry contract fields",
        provider=provider_id,
    )


def _check_provider_effort_compat(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    provider = registry["providers"][provider_id]
    effort = provider.get("effort", {})
    if effort.get("kind") == "none":
        return DoctorCheck(
            id=f"provider.{provider_id}.effort_compat",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"{provider_id} exposes no per-invocation effort control",
            provider=provider_id,
        )
    values = effort.get("values", [])
    if not values:
        return DoctorCheck(
            id=f"provider.{provider_id}.effort_compat",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"{provider_id} effort values are provider-defined (no registry list to validate)",
            provider=provider_id,
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.effort_compat",
        category=PROVIDER_CATEGORY,
        status="PASS",
        summary=f"{provider_id} effort values: {', '.join(values)}",
        provider=provider_id,
        details={"values": list(values)},
    )


def _check_provider_config_probe(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
    subprocess_runner: Callable[..., Any] | None = None,
) -> DoctorCheck:
    del repo_root
    provider = registry["providers"][provider_id]
    capabilities = provider.get("capabilities", {})
    if not capabilities.get("configProbe"):
        return DoctorCheck(
            id=f"provider.{provider_id}.config_probe",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"{provider_id} does not declare a read-only configuration probe",
            provider=provider_id,
        )
    home = Path(env.get("HOME", "~")).expanduser()
    adapter = get_adapter(provider_id)
    binary = adapter.resolve_binary(env, home)
    if binary is None:
        return DoctorCheck(
            id=f"provider.{provider_id}.config_probe",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"no {provider_id} binary to run the configuration probe",
            provider=provider_id,
            remediation=f"install the {provider_id} CLI or set the appropriate override",
        )
    probe_argv = _DOCUMENTED_CONFIG_PROBES.get(provider_id)
    if probe_argv is None:
        return DoctorCheck(
            id=f"provider.{provider_id}.config_probe",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"no documented read-only configuration probe is defined for {provider_id}",
            provider=provider_id,
        )
    argv = [binary, *probe_argv]
    runner = subprocess_runner or subprocess.run
    try:
        result = runner(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            timeout=10.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DoctorCheck(
            id=f"provider.{provider_id}.config_probe",
            category=PROVIDER_CATEGORY,
            status="WARN",
            summary=f"configuration probe for {provider_id} failed to execute: {exc}",
            remediation=f"run `{' '.join(argv)}` manually and repair the provider configuration",
            provider=provider_id,
        )
    exit_code = getattr(result, "returncode", None)
    if exit_code == 0:
        return DoctorCheck(
            id=f"provider.{provider_id}.config_probe",
            category=PROVIDER_CATEGORY,
            status="PASS",
            summary=f"{provider_id} read-only configuration probe succeeded",
            provider=provider_id,
            details={"exitCode": 0, "argv": argv},
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.config_probe",
        category=PROVIDER_CATEGORY,
        status="WARN",
        summary=f"{provider_id} configuration probe exited {exit_code}",
        remediation=f"run `{' '.join(argv)}` manually and repair the provider configuration",
        provider=provider_id,
        details={"exitCode": exit_code, "argv": argv},
    )


def _check_provider_auth_probe(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
    live_auth: bool,
    subprocess_runner: Callable[..., Any] | None = None,
) -> DoctorCheck:
    provider = registry["providers"][provider_id]
    capabilities = provider.get("capabilities", {})
    if not capabilities.get("authProbe"):
        return DoctorCheck(
            id=f"provider.{provider_id}.auth_probe",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"{provider_id} does not declare authProbe in the registry",
            provider=provider_id,
        )
    if not live_auth:
        return DoctorCheck(
            id=f"provider.{provider_id}.auth_probe",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"{provider_id} auth probe skipped (pass --live-auth to enable)",
            remediation=(
                f"rerun model-routing doctor --provider {provider_id} --live-auth to invoke the documented "
                f"read-only {provider_id} authentication probe"
            ),
            provider=provider_id,
        )
    home = Path(env.get("HOME", "~")).expanduser()
    adapter = get_adapter(provider_id)
    binary = adapter.resolve_binary(env, home)
    runner = subprocess_runner or subprocess.run
    if binary is None:
        return DoctorCheck(
            id=f"provider.{provider_id}.auth_probe",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=f"no {provider_id} binary to probe; install the CLI or set the override to a real executable",
            provider=provider_id,
            remediation=f"install the {provider_id} CLI or set the appropriate override",
        )
    probe_argv = _documented_auth_probe(provider_id)
    if probe_argv is None:
        return DoctorCheck(
            id=f"provider.{provider_id}.auth_probe",
            category=PROVIDER_CATEGORY,
            status="SKIP",
            summary=(
                f"no documented read-only auth probe is defined for {provider_id}; "
                "skipping to avoid mutating provider configuration"
            ),
            remediation=(
                f"consult the {provider_id} documentation for the canonical read-only auth command and "
                "add it to doctor._DOCUMENTED_AUTH_PROBES if appropriate"
            ),
            provider=provider_id,
        )
    argv = [binary, *probe_argv]
    try:
        result = runner(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            timeout=10.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DoctorCheck(
            id=f"provider.{provider_id}.auth_probe",
            category=PROVIDER_CATEGORY,
            status="WARN",
            summary=f"auth probe for {provider_id} failed to execute: {exc}",
            remediation=(
                f"verify the {provider_id} CLI is functional; the probe argv was {argv!r}"
            ),
            provider=provider_id,
        )
    exit_code = getattr(result, "returncode", None)
    stdout = getattr(result, "stdout", b"") or b""
    stderr = getattr(result, "stderr", b"") or b""
    output = (stdout + stderr).decode("utf-8", errors="replace").lower()
    if exit_code == 0:
        status, summary = "PASS", f"{provider_id} read-only auth probe succeeded"
    else:
        status, summary = "WARN", (
            f"{provider_id} read-only auth probe exited {exit_code}; the probe argv was {argv!r}"
        )
    return DoctorCheck(
        id=f"provider.{provider_id}.auth_probe",
        category=PROVIDER_CATEGORY,
        status=status,
        summary=summary,
        remediation=(
            f"re-authenticate {provider_id} (e.g. `login`) and rerun model-routing doctor --live-auth"
            if status != "PASS"
            else None
        ),
        provider=provider_id,
        details={"exitCode": exit_code, "argv": argv, "excerpt": output[:512]},
    )


_DOCUMENTED_AUTH_PROBES: dict[str, tuple[str, ...]] = {
    "claude": ("auth", "status"),
    "codex": ("login", "status"),
}

_DOCUMENTED_CONFIG_PROBES: dict[str, tuple[str, ...]] = {
    "kimi": ("doctor", "config"),
}


def _documented_auth_probe(provider_id: str) -> tuple[str, ...] | None:
    return _DOCUMENTED_AUTH_PROBES.get(provider_id)


def _check_plugin_marketplace(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    host_id: str,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    hosts = registry.get("hosts", {})
    host = hosts.get(host_id)
    if host is None:
        return DoctorCheck(
            id=f"plugin.{host_id}.marketplace_present",
            category=PLUGIN_CATEGORY,
            status="SKIP",
            summary=f"no host entry for {host_id} in the registry",
            provider=None,
        )
    package_path = repo_root / host["packagePath"]
    if not package_path.is_dir():
        return DoctorCheck(
            id=f"plugin.{host_id}.marketplace_present",
            category=PLUGIN_CATEGORY,
            status="WARN",
            summary=f"{host_id} host package directory missing at {package_path}",
            remediation=(
                f"restore plugins/{package_path.name} (host={host_id}) from the upstream checkout, "
                "or remove the host from config/provider-registry.json"
            ),
            details={"path": str(package_path)},
        )
    package_id = package_path.name
    manifest: Path | None = None
    candidates = [
        package_path / ".claude-plugin" / "plugin.json",
        package_path / ".codex-plugin" / "plugin.json",
        package_path / "plugin.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            manifest = candidate
            break
    if manifest is None:
        return DoctorCheck(
            id=f"plugin.{host_id}.marketplace_present",
            category=PLUGIN_CATEGORY,
            status="WARN",
            summary=f"{host_id} package has no plugin manifest under {package_path}",
            remediation=(
                f"create one of `plugin.json`, `.claude-plugin/plugin.json`, or `.codex-plugin/plugin.json` "
                f"inside {package_id} so the host can load the routing skills"
            ),
        )
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return DoctorCheck(
            id=f"plugin.{host_id}.marketplace_present",
            category=PLUGIN_CATEGORY,
            status="FAIL",
            summary=f"{host_id} plugin manifest is not valid JSON: {exc.msg}",
            remediation=f"repair {manifest} so it parses as JSON",
            details={"path": str(manifest)},
        )
    name = manifest_data.get("name") if isinstance(manifest_data, dict) else None
    version = manifest_data.get("version") if isinstance(manifest_data, dict) else None
    if not name or not version:
        return DoctorCheck(
            id=f"plugin.{host_id}.marketplace_present",
            category=PLUGIN_CATEGORY,
            status="FAIL",
            summary=f"{host_id} manifest must declare name and version",
            remediation=f"add `name` and `version` fields to {manifest}",
        )
    return DoctorCheck(
        id=f"plugin.{host_id}.marketplace_present",
        category=PLUGIN_CATEGORY,
        status="PASS",
        summary=f"{host_id} package found at {package_id} (name={name}, version={version})",
        details={"manifest": str(manifest), "name": name, "version": version},
    )


def _check_plugin_native_host_exclusions(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    host_id: str,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    host = registry.get("hosts", {}).get(host_id)
    if host is None:
        return DoctorCheck(
            id=f"plugin.{host_id}.native_host_exclusions",
            category=PLUGIN_CATEGORY,
            status="SKIP",
            summary=f"no host entry for {host_id} in the registry",
        )
    package_path = repo_root / host["packagePath"]
    native = [n for n in host.get("nativeProviders", []) if n]
    if not package_path.is_dir():
        return DoctorCheck(
            id=f"plugin.{host_id}.native_host_exclusions",
            category=PLUGIN_CATEGORY,
            status="SKIP",
            summary=f"{host_id} package not present; native-host exclusion check is moot",
        )
    if not native:
        return DoctorCheck(
            id=f"plugin.{host_id}.native_host_exclusions",
            category=PLUGIN_CATEGORY,
            status="PASS",
            summary=f"{host_id} declares no native providers; no exclusion needed",
        )
    return DoctorCheck(
        id=f"plugin.{host_id}.native_host_exclusions",
        category=PLUGIN_CATEGORY,
        status="PASS",
        summary=f"{host_id} native providers: {', '.join(native)} (excluded from generated routes)",
        details={"nativeProviders": list(native)},
    )


def _check_plugin_runtime_reference_shared(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    bundles: dict[str, Path] = {}
    for host_id, host in registry.get("hosts", {}).items():
        package_path = repo_root / host["packagePath"] / "skills" / "subagent-model-routing" / "references" / "model-prompting.md"
        if not package_path.is_file():
            continue
        bundles[host_id] = package_path
    if len(bundles) < 2:
        return DoctorCheck(
            id="plugin.runtime_reference_shared",
            category=PLUGIN_CATEGORY,
            status="SKIP",
            summary="fewer than two host bundles present; cannot compare the package-local model-prompting.md",
            details={"bundles": {key: str(value) for key, value in bundles.items()}},
        )
    reference = None
    mismatches: list[dict[str, str]] = []
    for host_id, path in sorted(bundles.items()):
        try:
            content = path.read_bytes()
        except OSError as exc:
            mismatches.append({"host": host_id, "path": str(path), "issue": f"unreadable: {exc}"})
            continue
        if reference is None:
            reference = content
            continue
        if content != reference:
            mismatches.append({"host": host_id, "path": str(path), "issue": "content differs from reference host"})
    if mismatches:
        return DoctorCheck(
            id="plugin.runtime_reference_shared",
            category=PLUGIN_CATEGORY,
            status="WARN",
            summary="package-local model-prompting.md is not byte-identical across hosts",
            remediation=(
                "sync the package-local references/model/model-prompting.md files so they share the canonical "
                "content; rerun model-routing doctor after a release-aligned regeneration"
            ),
            details={"mismatches": mismatches},
        )
    return DoctorCheck(
        id="plugin.runtime_reference_shared",
        category=PLUGIN_CATEGORY,
        status="PASS",
        summary=f"{len(bundles)} package-local model-prompting.md files are byte-identical",
        details={"hosts": sorted(bundles)},
    )


def _check_plugin_version_alignment(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    registry: Mapping[str, Any],
) -> DoctorCheck:
    versions: dict[str, str] = {}
    missing: list[str] = []
    for host_id, host in registry.get("hosts", {}).items():
        package_path = repo_root / host["packagePath"]
        manifest: Path | None = None
        for candidate in (
            package_path / ".claude-plugin" / "plugin.json",
            package_path / ".codex-plugin" / "plugin.json",
            package_path / "plugin.json",
        ):
            if candidate.is_file():
                manifest = candidate
                break
        if manifest is None:
            missing.append(host_id)
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            missing.append(host_id)
            continue
        version = data.get("version") if isinstance(data, dict) else None
        if not version:
            missing.append(host_id)
            continue
        versions[host_id] = str(version)
    if not versions:
        return DoctorCheck(
            id="plugin.version_alignment",
            category=PLUGIN_CATEGORY,
            status="WARN",
            summary="no host package manifests could be read; cannot compare versions",
        )
    unique = set(versions.values())
    if len(unique) > 1:
        return DoctorCheck(
            id="plugin.version_alignment",
            category=PLUGIN_CATEGORY,
            status="WARN",
            summary=f"host package versions are out of sync: {versions}",
            remediation=(
                "bump the lagging packages so all host plugins share the same version; "
                "rerun model-routing doctor after a coordinated release"
            ),
            details={"versions": versions},
        )
    return DoctorCheck(
        id="plugin.version_alignment",
        category=PLUGIN_CATEGORY,
        status="PASS",
        summary=f"all host package versions align on {next(iter(unique))}",
        details={"versions": versions, "missing": missing},
    )


def _check_security_unrestricted_mode(
    repo_root: Path,
    env: Mapping[str, str],
) -> DoctorCheck:
    value = env.get("SUBAGENT_MODEL_ROUTING_UNRESTRICTED")
    if value is None:
        return DoctorCheck(
            id="security.unrestricted_mode",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary=(
                "SUBAGENT_MODEL_ROUTING_UNRESTRICTED is unset; the runtime default is "
                "unrestricted provider execution"
            ),
            remediation=(
                "set SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0 to retain each provider CLI's "
                "sandbox and approval policy"
            ),
            details={"value": None},
        )
    if value == "1":
        return DoctorCheck(
            id="security.unrestricted_mode",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary="SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1 enables unrestricted provider flags",
            remediation=(
                "set SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0 for restricted execution, or document "
                "the explicit opt-in if the wider sandbox is required"
            ),
            details={"value": value},
        )
    if value == "0":
        return DoctorCheck(
            id="security.unrestricted_mode",
            category=SECURITY_CATEGORY,
            status="PASS",
            summary="SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0 keeps restricted provider flags",
            details={"value": value},
        )
    return DoctorCheck(
        id="security.unrestricted_mode",
        category=SECURITY_CATEGORY,
        status="WARN",
        summary=f"SUBAGENT_MODEL_ROUTING_UNRESTRICTED={value!r} is not a recognized value",
        remediation="set SUBAGENT_MODEL_ROUTING_UNRESTRICTED to 0 (restricted) or 1 (unrestricted)",
        details={"value": value},
    )


def _world_readable_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for filename in filenames:
            candidate = Path(dirpath) / filename
            try:
                mode = candidate.stat().st_mode
            except OSError:
                continue
            if mode & WORLD_BITS:
                found.append(str(candidate))
                continue
        if dirnames:
            for dirname in dirnames:
                candidate = Path(dirpath) / dirname
                try:
                    mode = candidate.stat().st_mode
                except OSError:
                    continue
                if mode & WORLD_BITS:
                    found.append(str(candidate))
    return found


def _check_security_world_readable_state(
    repo_root: Path,
    env: Mapping[str, str],
) -> DoctorCheck:
    root = state_root(env) / "runs"
    if not root.is_dir():
        return DoctorCheck(
            id="security.state_files_world_readable",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary=f"no run directory yet at {root}; world-readability probe deferred until first dispatch",
        )
    exposed = _world_readable_files(root)
    if exposed:
        return DoctorCheck(
            id="security.state_files_world_readable",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary=f"{len(exposed)} state artifact(s) are readable by other users",
            remediation=(
                "run `chmod 700` on dispatch directories and `chmod 600` on the contained files; "
                "rerun `model-routing doctor` after rotating permissions"
            ),
            details={"paths": exposed[:25]},
        )
    return DoctorCheck(
        id="security.state_files_world_readable",
        category=SECURITY_CATEGORY,
        status="PASS",
        summary="no world-readable state artifacts under the runs directory",
    )


def _check_security_world_readable_hooks(
    repo_root: Path,
    env: Mapping[str, str],
) -> DoctorCheck:
    path = config_root(env) / "hooks.json"
    if not path.exists():
        return DoctorCheck(
            id="security.hooks_world_readable",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary=f"no hooks.json at {path}; nothing to mask",
        )
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        return DoctorCheck(
            id="security.hooks_world_readable",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary=f"cannot stat hooks.json: {exc}",
            remediation=f"verify file accessibility at {path}",
        )
    if mode & WORLD_BITS:
        return DoctorCheck(
            id="security.hooks_world_readable",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary=f"hooks.json is readable by other users ({oct(mode & 0o777)})",
            remediation=f"run `chmod 600 {path}` so hook definitions stay private",
            details={"path": str(path), "mode": oct(mode & 0o777)},
        )
    return DoctorCheck(
        id="security.hooks_world_readable",
        category=SECURITY_CATEGORY,
        status="PASS",
        summary="hooks.json is private",
        details={"path": str(path)},
    )


def _check_security_retained_prompts(
    repo_root: Path,
    env: Mapping[str, str],
) -> DoctorCheck:
    root = state_root(env) / "runs"
    if not root.is_dir():
        return DoctorCheck(
            id="security.retained_prompts",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary="no run directory yet; retained-prompt scan deferred",
        )
    retained: list[str] = []
    for run_dir in root.iterdir():
        candidate = run_dir / "prompt.md"
        if candidate.is_file():
            try:
                if candidate.stat().st_size > 0:
                    retained.append(str(candidate))
            except OSError:
                continue
    if not retained:
        return DoctorCheck(
            id="security.retained_prompts",
            category=SECURITY_CATEGORY,
            status="PASS",
            summary="no retained prompt files under the runs directory",
        )
    return DoctorCheck(
        id="security.retained_prompts",
        category=SECURITY_CATEGORY,
        status="WARN",
        summary=f"{len(retained)} retained prompt file(s) under the runs directory",
        remediation=(
            "reminder: prompt bodies are only retained when --routing-retain-prompt is explicit; "
            "delete with `model-routing runs cleanup --all` if you want them removed"
        ),
        details={"paths": retained[:25]},
    )


def _check_security_oversized_state(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    max_bytes: int = DEFAULT_OVERSIZED_STATE_BYTES,
) -> DoctorCheck:
    root = state_root(env)
    if not root.is_dir():
        return DoctorCheck(
            id="security.oversized_state",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary=f"no state directory yet at {root}; size probe deferred",
        )
    total = 0
    breakdown: dict[str, int] = {}
    for sub in ("runs",):
        candidate = root / sub
        if not candidate.is_dir():
            continue
        bytes_total = 0
        for dirpath, _dirnames, filenames in os.walk(candidate):
            for filename in filenames:
                try:
                    bytes_total += (Path(dirpath) / filename).stat().st_size
                except OSError:
                    continue
        breakdown[sub] = bytes_total
        total += bytes_total
    if total > max_bytes:
        return DoctorCheck(
            id="security.oversized_state",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary=f"state tree consumes {total} bytes (threshold {max_bytes})",
            remediation=(
                "rotate old runs with `model-routing runs cleanup --older-than DAYS` or "
                "`model-routing runs cleanup --all` to reclaim disk space"
            ),
            details={"bytes": total, "threshold": max_bytes, "byArea": breakdown},
        )
    return DoctorCheck(
        id="security.oversized_state",
        category=SECURITY_CATEGORY,
        status="PASS",
        summary=f"state tree consumes {total} bytes (threshold {max_bytes})",
        details={"bytes": total, "byArea": breakdown},
    )


def _check_security_shell_wrapper_hooks(
    repo_root: Path,
    env: Mapping[str, str],
) -> DoctorCheck:
    path = config_root(env) / "hooks.json"
    if not path.exists():
        return DoctorCheck(
            id="security.shell_wrapper_hooks",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary=f"no hooks.json at {path}; shell-wrapper probe moot",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DoctorCheck(
            id="security.shell_wrapper_hooks",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary="hooks.json is not valid JSON; hook-shape audit deferred until it parses",
        )
    findings: list[str] = []
    shell_names = ("bash", "sh", "zsh", "fish", "dash", "ksh", "csh")
    if isinstance(data, dict):
        for event, definitions in data.items():
            if not isinstance(definitions, list):
                continue
            for index, definition in enumerate(definitions):
                if not isinstance(definition, dict):
                    continue
                command = definition.get("command")
                if not isinstance(command, list) or not command:
                    continue
                head = command[0]
                if isinstance(head, str) and Path(head).name in shell_names:
                    findings.append(f"{event}[{index}] -> {head}")
    if findings:
        return DoctorCheck(
            id="security.shell_wrapper_hooks",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary=f"{len(findings)} hook definition(s) invoke a shell directly",
            remediation=(
                "prefer argv-style hook commands (e.g. `/usr/bin/python3 -c ...`) so quoting and "
                "argument parsing are deterministic; rewrite shell wrappers before the next release"
            ),
            details={"hooks": findings},
        )
    return DoctorCheck(
        id="security.shell_wrapper_hooks",
        category=SECURITY_CATEGORY,
        status="PASS",
        summary="no hook definitions invoke a shell directly",
    )


def _check_security_worktree_cleanup_backlog(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    threshold: int = DEFAULT_WORKTREE_BACKLOG_COUNT,
) -> DoctorCheck:
    parent = state_root(env).parent
    if not parent.is_dir():
        return DoctorCheck(
            id="security.worktree_cleanup_backlog",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary=f"state root parent {parent} does not exist; worktree probe deferred",
        )
    worktrees_root = state_root(env) / "worktrees"
    if not worktrees_root.is_dir():
        return DoctorCheck(
            id="security.worktree_cleanup_backlog",
            category=SECURITY_CATEGORY,
            status="SKIP",
            summary="no worktrees directory yet; backlog probe deferred",
        )
    backlog = [path for path in worktrees_root.iterdir() if path.is_dir()]
    if len(backlog) > threshold:
        return DoctorCheck(
            id="security.worktree_cleanup_backlog",
            category=SECURITY_CATEGORY,
            status="WARN",
            summary=f"{len(backlog)} worktree entries exceed cleanup threshold ({threshold})",
            remediation=(
                "inspect the owning run and use `model-routing runs discard <id> --yes`; "
                "worktrees are never removed automatically"
            ),
            details={"count": len(backlog)},
        )
    return DoctorCheck(
        id="security.worktree_cleanup_backlog",
        category=SECURITY_CATEGORY,
        status="PASS",
        summary=f"{len(backlog)} worktree entries (threshold {threshold})",
        details={"count": len(backlog)},
    )


def _provider_checks(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider_id: str,
    registry: Mapping[str, Any],
    live_auth: bool,
) -> list[DoctorCheck]:
    return [
        _check_provider_binary_resolved(repo_root, env, provider_id=provider_id),
        _check_provider_executable_bit(repo_root, env, provider_id=provider_id, registry=registry),
        _check_provider_cli_contract(repo_root, env, provider_id=provider_id),
        _check_provider_binary_override(repo_root, env, provider_id=provider_id, registry=registry),
        _check_provider_default_model(repo_root, env, provider_id=provider_id, registry=registry),
        _check_provider_contract_drift(repo_root, env, provider_id=provider_id, registry=registry),
        _check_provider_effort_compat(repo_root, env, provider_id=provider_id, registry=registry),
        _check_provider_config_probe(
            repo_root,
            env,
            provider_id=provider_id,
            registry=registry,
        ),
        _check_provider_auth_probe(
            repo_root,
            env,
            provider_id=provider_id,
            registry=registry,
            live_auth=live_auth,
        ),
    ]


def _plugin_checks(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    registry: Mapping[str, Any],
) -> list[DoctorCheck]:
    hosts = registry.get("hosts", {})
    per_host = [_check_plugin_marketplace(repo_root, env, host_id=host_id, registry=registry) for host_id in hosts]
    per_host.extend(
        [_check_plugin_native_host_exclusions(repo_root, env, host_id=host_id, registry=registry) for host_id in hosts]
    )
    aggregates = [
        _check_plugin_runtime_reference_shared(repo_root, env, registry=registry),
        _check_plugin_version_alignment(repo_root, env, registry=registry),
    ]
    return per_host + aggregates


def _runtime_checks(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    registry: Mapping[str, Any],
) -> list[DoctorCheck]:
    return [
        _check_python_version(repo_root, env),
        _check_git(repo_root, env),
        _check_state_dir(repo_root, env),
        _check_ledger_parent(repo_root, env),
        _check_generated_routes(repo_root, env, registry),
        _check_install_links(repo_root, env),
        _check_hooks_config(repo_root, env),
    ]


def _security_checks(
    repo_root: Path,
    env: Mapping[str, str],
) -> list[DoctorCheck]:
    return [
        _check_security_unrestricted_mode(repo_root, env),
        _check_security_world_readable_state(repo_root, env),
        _check_security_world_readable_hooks(repo_root, env),
        _check_security_retained_prompts(repo_root, env),
        _check_security_oversized_state(repo_root, env),
        _check_security_shell_wrapper_hooks(repo_root, env),
        _check_security_worktree_cleanup_backlog(repo_root, env),
    ]


def _filter_checks(checks: Iterable[DoctorCheck], *, provider: str | None) -> list[DoctorCheck]:
    if provider is None:
        return list(checks)
    filtered: list[DoctorCheck] = []
    for check in checks:
        if check.category == PROVIDER_CATEGORY:
            if check.provider != provider:
                continue
        if check.category == PLUGIN_CATEGORY and check.provider is not None and check.provider != provider:
            continue
        filtered.append(check)
    return filtered


def run_doctor(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    provider: str | None = None,
    installation_only: bool = False,
    live_auth: bool = False,
    discover_models: bool = False,
) -> dict[str, Any]:
    """Run a deterministic, read-only doctor and return the JSON-serializable report."""

    if installation_only and discover_models:
        raise ValueError("--installation-only cannot be combined with --discover-models")
    repo_root = Path(repo_root)
    candidate_providers = sorted(adapter_ids())
    if provider is not None:
        resolved = _resolve_provider_filter(provider, available_providers=candidate_providers)
        if resolved is not None:
            provider = resolved

    registry, registry_failure = _read_registry(repo_root)
    checks: list[DoctorCheck] = []
    if registry_failure is not None:
        checks.append(registry_failure)
    elif installation_only:
        assert registry is not None
        checks.extend(_runtime_checks(repo_root, env, registry=registry))
    else:
        assert registry is not None
        checks.extend(_runtime_checks(repo_root, env, registry=registry))
        target_providers = [provider] if provider is not None else candidate_providers
        for provider_id in target_providers:
            checks.extend(
                _provider_checks(
                    repo_root,
                    env,
                    provider_id=provider_id,
                    registry=registry,
                    live_auth=live_auth,
                )
            )
        if discover_models:
            for discovered_check in run_model_discovery(repo_root, env, registry, provider=provider):
                checks.append(
                    DoctorCheck(
                        id=discovered_check["id"],
                        category=discovered_check["category"],
                        status=discovered_check["status"],
                        summary=discovered_check["summary"],
                        remediation=discovered_check.get("remediation"),
                        provider=discovered_check.get("provider"),
                        details=discovered_check.get("details"),
                    )
                )
        checks.extend(_plugin_checks(repo_root, env, registry=registry))
        checks.extend(_security_checks(repo_root, env))

    filtered = _filter_checks(checks, provider=provider)

    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for check in filtered:
        normalized = check.status.upper()
        if normalized not in VALID_STATUSES:
            normalized = "FAIL"
        counts[normalized.lower()] = counts.get(normalized.lower(), 0) + 1

    normalized_checks: list[DoctorCheck] = []
    for check in filtered:
        status = check.status.upper()
        if status not in VALID_STATUSES:
            status = "FAIL"
        normalized_checks.append(
            DoctorCheck(
                id=check.id,
                category=check.category,
                status=status,
                summary=check.summary,
                remediation=check.remediation,
                provider=check.provider,
                details=check.details,
            )
        )

    modes = {
        "installationOnly": bool(installation_only),
        "liveAuth": bool(live_auth),
        "discoverModels": bool(discover_models),
        "providerFilter": provider,
    }

    report = DoctorReport(
        modes=modes,
        status=_status_from_counts(counts),
        summary=counts,
        checks=normalized_checks,
        generated_at=_now_iso(),
    )
    return report.to_dict()
