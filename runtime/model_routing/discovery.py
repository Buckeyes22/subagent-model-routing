"""Explicit model-discovery backend for `model-routing doctor --discover-models`.

Invoked only from an explicit CLI mode. Module-level code performs no probes
and writes no files. Every executable that may leak the user's environment is
launched through a tightly constrained subprocess call whose argv (and only
argv) is recorded. Raw output, environment variables, tokens, and credentials
are never copied into the returned check payload.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .process import run_bounded_capture


MAX_OUTPUT_BYTES = 1024 * 1024  # 1 MiB
OPENCODE_TIMEOUT = 20.0
KIMI_TIMEOUT = 10.0

_MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_LIST_FIRST_TOKEN = re.compile(r"^\s*([^\s]+)")
# Conservative signal: model identifiers must include a digit, slash, hyphen,
# dot, or underscore so we reject conversational noise ("this", "output", …).
_MODEL_ID_SIGNAL = re.compile(r"[0-9._/-]")

_OPENCODE_PROBE = ("models",)
_KIMI_PROBE = ("provider", "list", "--json")
_OUTPUT_CANDIDATE_KEYS = (
    "id",
    "model",
    "slug",
    "name",
    "model_id",
    "modelId",
)


def _configured_models(registry: Mapping[str, Any], provider_id: str) -> list[str]:
    provider = registry.get("providers", {}).get(provider_id, {})
    models = provider.get("models", {})
    return sorted(models.keys()) if isinstance(models, Mapping) else []


def _coerce_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("HOME") or "~").expanduser()


def _check_id(provider_id: str) -> str:
    return f"provider.{provider_id}.models_discovery"


def _build_check(
    *,
    provider_id: str,
    status: str,
    summary: str,
    source: str,
    command: list[str] | None,
    models: list[str],
    configured: list[str],
    remediation: str | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "source": source,
        "command": command,
        "models": sorted(dict.fromkeys(models)),
        "configuredModels": sorted(dict.fromkeys(configured)),
    }
    return {
        "id": _check_id(provider_id),
        "category": "provider",
        "provider": provider_id,
        "status": status,
        "summary": summary,
        "remediation": remediation,
        "details": details,
    }


def _select_target_providers(
    registry: Mapping[str, Any],
    provider: str | None,
) -> list[str]:
    available = sorted(registry.get("providers", {}).keys())
    if provider is None:
        return available
    if provider not in set(available):
        raise ValueError(f"unknown provider: {provider!r}")
    return [provider]


def discover_models(
    repo_root: Path,
    env: Mapping[str, str],
    registry: Mapping[str, Any],
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Return one JSON-friendly check per registry provider, honoring an optional filter."""

    del repo_root  # Discovery is local-only; explicit arg retained for API symmetry.
    target_providers = _select_target_providers(registry, provider)
    checks: list[dict[str, Any]] = []
    for provider_id in target_providers:
        configured = _configured_models(registry, provider_id)
        checks.append(_discover_for_provider(provider_id, env, configured))
    return checks


def _discover_for_provider(
    provider_id: str,
    env: Mapping[str, str],
    configured: list[str],
) -> dict[str, Any]:
    if provider_id == "opencode":
        return _discover_opencode(env, configured)
    if provider_id == "codex":
        return _discover_codex(env, configured)
    if provider_id == "kimi":
        return _discover_kimi(env, configured)
    if provider_id in {"claude", "grok"}:
        return _build_check(
            provider_id=provider_id,
            status="SKIP",
            summary=(
                f"{provider_id} does not expose a stable model-list command; "
                "skipping live discovery"
            ),
            source="unsupported",
            command=None,
            models=list(configured),
            configured=configured,
        )
    return _build_check(
        provider_id=provider_id,
        status="WARN",
        summary=f"unknown provider {provider_id!r} for discovery",
        source="unsupported",
        command=None,
        models=[],
        configured=configured,
    )


def _resolve_opencode_binary(env: Mapping[str, str]) -> str | None:
    from model_routing.providers import get_adapter

    home = _coerce_home(env)
    binary = get_adapter("opencode").resolve_binary(env, home)
    if not binary:
        return None
    if os.path.isabs(binary) and os.path.isfile(binary):
        return binary
    discovered = get_adapter("opencode").which(binary, env)
    if discovered and os.path.isfile(discovered):
        return discovered
    if os.path.isabs(binary) and os.access(binary, os.X_OK):
        return binary
    return None


def _resolve_kimi_binary(env: Mapping[str, str]) -> str | None:
    from model_routing.providers import get_adapter

    adapter = get_adapter("kimi")
    binary = adapter.resolve_binary(env, _coerce_home(env))
    if not binary:
        return None
    if os.path.isabs(binary) and os.path.isfile(binary) and os.access(binary, os.X_OK):
        return binary
    discovered = adapter.which(binary, env)
    return discovered if discovered and os.path.isfile(discovered) else None


def _kimi_model_aliases(raw: bytes, env: Mapping[str, str]) -> list[str]:
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    models = payload.get("models") if isinstance(payload, Mapping) else None
    candidates = list(models) if isinstance(models, Mapping) else []
    environment_model = env.get("KIMI_MODEL_NAME")
    if environment_model:
        candidates.append(environment_model)
    return sorted(
        {
            candidate
            for candidate in candidates
            if isinstance(candidate, str)
            and _MODEL_ID_PATTERN.fullmatch(candidate) is not None
        }
    )


def _discover_kimi(
    env: Mapping[str, str],
    configured: list[str],
) -> dict[str, Any]:
    binary = _resolve_kimi_binary(env)
    if binary is None:
        return _build_check(
            provider_id="kimi",
            status="WARN",
            summary="Kimi Code CLI is not installed or not on PATH; cannot list configured models",
            source="live-kimi-config",
            command=None,
            models=[],
            configured=configured,
            remediation="install Kimi Code or set KIMI_BIN to the resolved binary path",
        )
    argv = [binary, *_KIMI_PROBE]
    try:
        result = run_bounded_capture(
            argv,
            env=dict(env),
            timeout_seconds=KIMI_TIMEOUT,
            max_bytes=MAX_OUTPUT_BYTES,
        )
    except OSError as exc:
        return _build_check(
            provider_id="kimi",
            status="WARN",
            summary=f"could not invoke `kimi provider list --json`: {exc}",
            source="live-kimi-config",
            command=argv,
            models=[],
            configured=configured,
            remediation="verify the Kimi Code binary is executable and reachable",
        )
    if getattr(result, "timed_out", False):
        return _build_check(
            provider_id="kimi",
            status="WARN",
            summary=f"`kimi provider list --json` exceeded {KIMI_TIMEOUT:.0f}s timeout",
            source="live-kimi-config",
            command=argv,
            models=[],
            configured=configured,
            remediation="rerun `kimi provider list` manually and verify Kimi Code configuration",
        )
    if result.returncode != 0:
        return _build_check(
            provider_id="kimi",
            status="WARN",
            summary=f"`kimi provider list --json` exited with status {result.returncode}",
            source="live-kimi-config",
            command=argv,
            models=[],
            configured=configured,
            remediation="run `kimi doctor config` and repair Kimi Code configuration",
        )
    models = _kimi_model_aliases(result.stdout or b"", env)
    if not models:
        return _build_check(
            provider_id="kimi",
            status="WARN",
            summary="Kimi Code provider inventory did not contain any model aliases",
            source="live-kimi-config",
            command=argv,
            models=[],
            configured=configured,
            remediation="configure a Kimi Code model or run `kimi login`, then retry discovery",
        )
    return _build_check(
        provider_id="kimi",
        status="PASS",
        summary=f"discovered {len(models)} configured Kimi Code model alias(es)",
        source="live-kimi-config",
        command=argv,
        models=models,
        configured=configured,
    )


def _discover_opencode(
    env: Mapping[str, str],
    configured: list[str],
) -> dict[str, Any]:
    binary = _resolve_opencode_binary(env)
    if binary is None:
        return _build_check(
            provider_id="opencode",
            status="WARN",
            summary="opencode CLI is not installed or not on PATH; cannot list models",
            source="live-opencode",
            command=None,
            models=[],
            configured=configured,
            remediation=(
                "install the opencode CLI or set OPENCODE_BIN to the resolved binary path"
            ),
        )
    argv = [binary, *_OPENCODE_PROBE]
    child_env: dict[str, str] = dict(env)
    try:
        result = run_bounded_capture(
            argv,
            env=child_env,
            timeout_seconds=OPENCODE_TIMEOUT,
            max_bytes=MAX_OUTPUT_BYTES,
        )
    except OSError as exc:
        return _build_check(
            provider_id="opencode",
            status="WARN",
            summary=f"could not invoke `opencode models`: {exc}",
            source="live-opencode",
            command=argv,
            models=[],
            configured=configured,
            remediation="verify the opencode binary is executable and reachable",
        )
    if getattr(result, "timed_out", False):
        return _build_check(
            provider_id="opencode",
            status="WARN",
            summary=(
                f"`opencode models` exceeded {OPENCODE_TIMEOUT:.0f}s timeout"
            ),
            source="live-opencode",
            command=argv,
            models=[],
            configured=configured,
            remediation=(
                "rerun the discovery command manually or increase the opencode timeout"
            ),
        )
    if result.returncode != 0:
        return _build_check(
            provider_id="opencode",
            status="WARN",
            summary=(
                f"`opencode models` exited with status {result.returncode}"
            ),
            source="live-opencode",
            command=argv,
            models=[],
            configured=configured,
            remediation=(
                "rerun `opencode models` manually and verify the installed CLI"
            ),
        )
    raw_stdout = result.stdout or b""
    raw_stderr = result.stderr or b""
    models = _parse_models_output(raw_stdout)
    if not models:
        return _build_check(
            provider_id="opencode",
            status="WARN",
            summary="opencode `models` output did not contain any model identifiers",
            source="live-opencode",
            command=argv,
            models=[],
            configured=configured,
            remediation=(
                "refresh the opencode CLI or rerun discovery to capture updated "
                "model identifiers"
            ),
        )
    _ = raw_stderr  # capped; never propagated into the check payload
    return _build_check(
        provider_id="opencode",
        status="PASS",
        summary=f"discovered {len(models)} opencode model identifier(s)",
        source="live-opencode",
        command=argv,
        models=models,
        configured=configured,
    )


def _parse_models_output(raw: bytes) -> list[str]:
    text = raw.decode("utf-8", errors="replace")
    candidates = _candidates_from_json(text)
    if not candidates:
        candidates = _candidates_from_lines(text)
    return _normalize_identifiers(candidates)


def _candidates_from_json(text: str) -> list[str]:
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped[0] not in "{[":
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _collect_model_candidates(payload)


def _collect_model_candidates(payload: Any) -> list[str]:
    found: list[str] = []
    if isinstance(payload, Mapping):
        for key in _OUTPUT_CANDIDATE_KEYS:
            value = payload.get(key)
            if isinstance(value, str):
                found.append(value)
        for key, value in payload.items():
            if key not in _OUTPUT_CANDIDATE_KEYS and isinstance(value, (Mapping, list)):
                found.extend(_collect_model_candidates(value))
        return found
    if isinstance(payload, list):
        for value in payload:
            found.extend(_collect_model_candidates(value))
        return found
    if isinstance(payload, str):
        found.append(payload)
    return found


def _candidates_from_lines(text: str) -> list[str]:
    results: list[str] = []
    for line in text.splitlines():
        match = _LIST_FIRST_TOKEN.match(line)
        if not match:
            continue
        token = match.group(1)
        token = token.strip(" \t\r\n\"'`")
        if not token:
            continue
        results.append(token)
    return results


def _normalize_identifiers(candidates: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = candidate.strip().strip("\"'`")
        if not cleaned:
            continue
        match = _MODEL_ID_PATTERN.match(cleaned)
        if not match:
            continue
        identifier = match.group(0)
        if not identifier or not _MODEL_ID_SIGNAL.search(identifier):
            continue
        if identifier not in seen:
            seen[identifier] = None
    return list(seen)


def _resolve_codex_cache_path(env: Mapping[str, str]) -> Path | None:
    override = env.get("CODEX_HOME")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override) / "models_cache.json")
    candidates.append(_coerce_home(env) / ".codex" / "models_cache.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _discover_codex(
    env: Mapping[str, str],
    configured: list[str],
) -> dict[str, Any]:
    cache_path = _resolve_codex_cache_path(env)
    if cache_path is None:
        return _build_check(
            provider_id="codex",
            status="WARN",
            summary="codex local model cache not found; cannot list installed models",
            source="local-cache",
            command=None,
            models=[],
            configured=configured,
            remediation=(
                "install codex or refresh its local model cache before rerunning discovery"
            ),
        )
    try:
        with cache_path.open("rb") as handle:
            raw_bytes = handle.read(MAX_OUTPUT_BYTES + 1)
    except OSError as exc:
        return _build_check(
            provider_id="codex",
            status="WARN",
            summary=f"cannot read codex model cache {cache_path}: {exc}",
            source="local-cache",
            command=None,
            models=[],
            configured=configured,
            remediation="verify the codex cache file is readable",
        )
    if len(raw_bytes) > MAX_OUTPUT_BYTES:
        return _build_check(
            provider_id="codex",
            status="WARN",
            summary=f"codex model cache {cache_path} exceeds the 1 MiB discovery limit",
            source="local-cache",
            command=None,
            models=[],
            configured=configured,
            remediation="refresh or inspect the oversized codex model cache before retrying discovery",
        )
    raw = raw_bytes.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _build_check(
            provider_id="codex",
            status="WARN",
            summary=f"codex model cache {cache_path} is not valid JSON",
            source="local-cache",
            command=None,
            models=[],
            configured=configured,
            remediation=(
                "delete or repair the cache file, then rerun discovery to rebuild "
                "the model list"
            ),
        )
    candidates = _collect_model_candidates(payload)
    models = _normalize_identifiers(candidates)
    if not models:
        return _build_check(
            provider_id="codex",
            status="WARN",
            summary=f"codex model cache {cache_path} did not yield any model identifiers",
            source="local-cache",
            command=None,
            models=[],
            configured=configured,
            remediation=(
                "force-refresh the codex cache or rerun discovery once the "
                "cache is regenerated"
            ),
        )
    return _build_check(
        provider_id="codex",
        status="PASS",
        summary=f"discovered {len(models)} codex model identifier(s) from {cache_path.name}",
        source="local-cache",
        command=None,
        models=models,
        configured=configured,
    )
