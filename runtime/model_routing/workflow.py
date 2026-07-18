"""Phase 6 workflow document loader, semantic validator, and digest.

The workflow document is a versioned JSON graph that names dispatch tasks,
their routes, prompts, dependencies, retry policy, and optional verification
commands. ``validate_workflow`` performs the structural and semantic checks
described in section 6.2 of the Phase 6 implementation plan and returns a
fully explicit normalized dictionary plus any advisory warnings (currently
limited to unknown model IDs when the provider opts in). ``load_workflow``
reads and validates a workflow file from disk. ``workflow_digest`` produces a
deterministic SHA-256 over the canonical JSON of the normalized output.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


class WorkflowError(ValueError):
    """Raised when a workflow document violates the runtime contract."""


_TASK_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_ARTIFACT_VALUES = {"stdout", "stderr", "result", "patch", "diffstat"}
_RETRY_TRIGGERS = {"timeout", "transport-error"}
_HOSTS = {"claude", "codex", "copilot"}
_WORKSPACES = {"shared", "isolated", "auto"}
_MODES = {"read", "write"}
_FAILURE_POLICIES = {"fail-fast", "continue"}


def _fail(message: str) -> None:
    raise WorkflowError(message)


def _require_keys(value: Mapping[str, Any], field: str, allowed: set[str]) -> None:
    extras = set(value) - allowed
    if extras:
        joined = ", ".join(sorted(extras))
        _fail(f"{field} has unknown fields: {joined}")


def _resolve_alias(
    provider_def: Mapping[str, Any], model: str
) -> tuple[str, bool]:
    """Resolve ``model`` against ``provider_def`` registry, case-insensitively.

    Returns ``(canonical_model, found)``. ``found`` is False when the model is
    not declared under the provider's ``models`` map or any of its aliases;
    callers decide whether unknown models are tolerated.
    """

    if not isinstance(provider_def, Mapping):
        return model, False
    models = provider_def.get("models")
    if not isinstance(models, Mapping):
        return model, False
    if model in models:
        return model, True
    lower = model.lower()
    for canonical, entry in models.items():
        if not isinstance(entry, Mapping):
            continue
        aliases = entry.get("aliases") or []
        for alias in aliases:
            if isinstance(alias, str) and alias and alias.lower() == lower:
                return canonical, True
    return model, False


def _validate_prompt_file(file_value: str, workflow_dir: Path, field: str) -> str:
    if not file_value:
        _fail(f"{field} must be a non-empty string")
    candidate = Path(file_value)
    if candidate.is_absolute():
        _fail(f"{field} must be a relative path: {file_value!r}")
    parts = candidate.parts
    if any(part == ".." for part in parts):
        _fail(f"{field} must not contain a parent path segment: {file_value!r}")
    real_dir = workflow_dir.resolve()
    resolved = (real_dir / file_value).resolve()
    try:
        resolved.relative_to(real_dir)
    except ValueError:
        _fail(f"{field} escapes workflow directory: {file_value!r}")
    if not resolved.is_file():
        _fail(f"{field} is not a regular file: {file_value!r}")
    return file_value


def _find_cycle(deps: Mapping[str, list[str]]) -> list[str] | None:
    """Return a cycle path like ``['a', 'b', 'c', 'a']`` or ``None``."""

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in deps}

    for start in deps:
        if color[start] != WHITE:
            continue
        path = [start]
        color[start] = GRAY
        stack = [(start, iter(deps.get(start, [])))]
        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if not isinstance(child, str):
                    continue
                if child not in color:
                    _fail(f"dependency references unknown task: {child!r}")
                if color[child] == GRAY:
                    if child in path:
                        idx = path.index(child)
                        return path[idx:] + [child]
                    return [child, node, child]
                if color[child] == WHITE:
                    color[child] = GRAY
                    path.append(child)
                    stack.append((child, iter(deps.get(child, []))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                path.pop()
                stack.pop()
    return None


def _validate_prompt(prompt: Any, task_name: str, workflow_dir: Path) -> dict[str, Any]:
    if not isinstance(prompt, Mapping):
        _fail(f"tasks.{task_name}.prompt must be an object")
    keys = set(prompt)
    if keys != {"file"} and keys != {"text"}:
        _fail(f"tasks.{task_name}.prompt must contain exactly one of 'file' or 'text'")
    if "file" in prompt:
        file_value = prompt["file"]
        if not isinstance(file_value, str) or not file_value:
            _fail(f"tasks.{task_name}.prompt.file must be a non-empty string")
        return {"file": _validate_prompt_file(file_value, workflow_dir, f"tasks.{task_name}.prompt.file")}
    text_value = prompt["text"]
    if not isinstance(text_value, str) or not text_value:
        _fail(f"tasks.{task_name}.prompt.text must be a non-empty string")
    return {"text": text_value}


def _normalize_route(
    route: Mapping[str, Any],
    *,
    task_name: str,
    registry_providers: Mapping[str, Any],
    native_providers: set[str],
    host: str,
    warnings: list[str],
) -> dict[str, Any]:
    if not isinstance(route, Mapping):
        _fail(f"tasks.{task_name}.route must be an object")
    _require_keys(route, f"tasks.{task_name}.route", {"provider", "model", "effort"})

    provider = route.get("provider")
    if not isinstance(provider, str) or not provider:
        _fail(f"tasks.{task_name}.route.provider must be a non-empty string")
    assert isinstance(provider, str)
    if provider not in registry_providers:
        _fail(f"tasks.{task_name}.route.provider {provider!r} is not a registered provider")
    if provider in native_providers:
        _fail(
            f"tasks.{task_name}.route.provider {provider!r} is native to host {host!r}; "
            "keep that work native to the host"
        )

    model = route.get("model")
    if not isinstance(model, str) or not model:
        _fail(f"tasks.{task_name}.route.model must be a non-empty string")
    assert isinstance(model, str)

    provider_def = registry_providers.get(provider, {})
    canonical_model, found = _resolve_alias(provider_def, model)
    allow_unknown = bool(provider_def.get("allowUnknownModels", False)) if isinstance(provider_def, Mapping) else False
    if not found:
        if allow_unknown:
            warnings.append(
                f"tasks.{task_name}.route.model {model!r} is not declared by provider {provider!r}; "
                "passing through because allowUnknownModels is true"
            )
        else:
            _fail(
                f"tasks.{task_name}.route.model {model!r} is not a known model of provider {provider!r}"
            )

    effort = route.get("effort")
    if effort is not None:
        if not isinstance(effort, str) or not effort:
            _fail(f"tasks.{task_name}.route.effort must be a non-empty string")
        effort_def = provider_def.get("effort") if isinstance(provider_def, Mapping) else None
        allowed = list(effort_def.get("values", [])) if isinstance(effort_def, Mapping) else []
        if effort not in allowed:
            _fail(
                f"tasks.{task_name}.route.effort {effort!r} is not allowed for provider {provider!r}"
            )
        if found and isinstance(provider_def, Mapping):
            models = provider_def.get("models")
            if isinstance(models, Mapping):
                entry = models.get(canonical_model)
                if isinstance(entry, Mapping):
                    model_effort = entry.get("effortValues") or []
                    if model_effort and effort not in model_effort:
                        _fail(
                            f"tasks.{task_name}.route.effort {effort!r} is not allowed for "
                            f"model {canonical_model!r} of provider {provider!r}"
                        )

    normalized: dict[str, Any] = {"provider": provider, "model": canonical_model}
    if effort is not None:
        normalized["effort"] = effort
    return dict(sorted(normalized.items()))


def _normalize_retry(retry: Any, task_name: str) -> dict[str, Any]:
    if retry is None:
        retry = {}
    if not isinstance(retry, Mapping):
        _fail(f"tasks.{task_name}.retry must be an object")
    _require_keys(retry, f"tasks.{task_name}.retry", {"maxAttempts", "backoffSeconds", "on"})
    max_attempts = retry.get("maxAttempts", 1)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        _fail(f"tasks.{task_name}.retry.maxAttempts must be a positive integer")
    backoff = retry.get("backoffSeconds", 0)
    if not isinstance(backoff, (int, float)) or isinstance(backoff, bool) or backoff < 0:
        _fail(f"tasks.{task_name}.retry.backoffSeconds must be a non-negative number")
    on = retry.get("on", [])
    if not isinstance(on, list):
        _fail(f"tasks.{task_name}.retry.on must be a list")
    seen: set[str] = set()
    normalized_on: list[str] = []
    for trigger in on:
        if not isinstance(trigger, str):
            _fail(f"tasks.{task_name}.retry.on entries must be strings")
        if trigger not in _RETRY_TRIGGERS:
            _fail(
                f"tasks.{task_name}.retry.on {trigger!r} must be one of {sorted(_RETRY_TRIGGERS)}"
            )
        if trigger in seen:
            _fail(f"tasks.{task_name}.retry.on duplicates {trigger!r}")
        seen.add(trigger)
        normalized_on.append(trigger)
    return {"maxAttempts": max_attempts, "backoffSeconds": backoff, "on": normalized_on}


def _normalize_verify(verify: Any, task_name: str) -> list[list[str]]:
    if verify is None:
        return []
    if not isinstance(verify, list):
        _fail(f"tasks.{task_name}.verify must be a list")
    normalized: list[list[str]] = []
    for index, command in enumerate(verify):
        if not isinstance(command, list) or not command:
            _fail(f"tasks.{task_name}.verify[{index}] must be a non-empty array of strings")
        argv: list[str] = []
        for arg_index, arg in enumerate(command):
            if not isinstance(arg, str) or not arg:
                _fail(f"tasks.{task_name}.verify[{index}][{arg_index}] must be a non-empty string")
            argv.append(arg)
        normalized.append(argv)
    return normalized


def _normalize_context_from(
    context_from: Any,
    *,
    task_name: str,
    direct_deps: set[str],
) -> list[dict[str, Any]]:
    if context_from is None:
        return []
    if not isinstance(context_from, list):
        _fail(f"tasks.{task_name}.contextFrom must be a list")
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(context_from):
        if not isinstance(entry, Mapping):
            _fail(f"tasks.{task_name}.contextFrom[{index}] must be an object")
        _require_keys(entry, f"tasks.{task_name}.contextFrom[{index}]", {"task", "artifact", "maxBytes"})
        ref = entry.get("task")
        if not isinstance(ref, str) or not ref:
            _fail(f"tasks.{task_name}.contextFrom[{index}].task must be a non-empty string")
        artifact = entry.get("artifact")
        if artifact not in _ARTIFACT_VALUES:
            _fail(
                f"tasks.{task_name}.contextFrom[{index}].artifact must be one of "
                f"{sorted(_ARTIFACT_VALUES)}"
            )
        if ref not in direct_deps:
            _fail(
                f"tasks.{task_name}.contextFrom[{index}].task {ref!r} is not a direct dependency"
            )
        max_bytes = entry.get("maxBytes", 50000)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            _fail(
                f"tasks.{task_name}.contextFrom[{index}].maxBytes must be a positive integer"
            )
        normalized.append({"task": ref, "artifact": artifact, "maxBytes": max_bytes})
    return normalized


def _normalize_task(
    task_name: str,
    task_def: Any,
    *,
    defaults: Mapping[str, Any],
    workflow_dir: Path,
    registry_providers: Mapping[str, Any],
    native_providers: set[str],
    host: str,
    warnings: list[str],
    task_names: set[str],
) -> dict[str, Any]:
    if not isinstance(task_def, Mapping):
        _fail(f"tasks.{task_name} must be an object")
    _require_keys(
        task_def,
        f"tasks.{task_name}",
        {
            "route", "mode", "prompt", "dependsOn", "contextFrom",
            "timeoutSeconds", "workspace", "retry", "verify",
        },
    )

    mode = task_def.get("mode")
    if mode not in _MODES:
        _fail(f"tasks.{task_name}.mode must be one of {sorted(_MODES)}")

    route = _normalize_route(
        task_def.get("route"),
        task_name=task_name,
        registry_providers=registry_providers,
        native_providers=native_providers,
        host=host,
        warnings=warnings,
    )

    prompt = _validate_prompt(task_def.get("prompt"), task_name, workflow_dir)

    depends_on_raw = task_def.get("dependsOn", [])
    if depends_on_raw is None:
        depends_on_raw = []
    if not isinstance(depends_on_raw, list):
        _fail(f"tasks.{task_name}.dependsOn must be a list")
    seen_dep: set[str] = set()
    normalized_deps: list[str] = []
    for dep in depends_on_raw:
        if not isinstance(dep, str) or not dep:
            _fail(f"tasks.{task_name}.dependsOn entries must be non-empty strings")
        if dep == task_name:
            _fail(f"task {task_name!r} depends on itself")
        if dep not in task_names:
            _fail(f"tasks.{task_name}.dependsOn references unknown task {dep!r}")
        if dep in seen_dep:
            _fail(f"tasks.{task_name}.dependsOn duplicates {dep!r}")
        seen_dep.add(dep)
        normalized_deps.append(dep)
    normalized_deps.sort()

    direct_deps = set(normalized_deps)
    context_from = _normalize_context_from(
        task_def.get("contextFrom"),
        task_name=task_name,
        direct_deps=direct_deps,
    )

    timeout_seconds = task_def.get("timeoutSeconds", defaults["timeoutSeconds"])
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        _fail(f"tasks.{task_name}.timeoutSeconds must be a positive number")

    workspace = task_def.get("workspace", defaults["workspace"])
    if workspace not in _WORKSPACES:
        _fail(f"tasks.{task_name}.workspace must be one of {sorted(_WORKSPACES)}")
    if mode == "write" and workspace == "shared":
        _fail(f"write task {task_name!r} cannot use workspace 'shared'")

    retry = _normalize_retry(task_def.get("retry"), task_name)
    verify = _normalize_verify(task_def.get("verify"), task_name)

    return {
        "route": route,
        "mode": mode,
        "prompt": prompt,
        "dependsOn": normalized_deps,
        "contextFrom": context_from,
        "timeoutSeconds": timeout_seconds,
        "workspace": workspace,
        "retry": retry,
        "verify": verify,
    }


def _normalize_defaults(raw_defaults: Any, registry_providers: Mapping[str, Any]) -> dict[str, Any]:
    if raw_defaults is None:
        return {
            "maxConcurrency": 2,
            "providerConcurrency": {},
            "timeoutSeconds": 1140,
            "workspace": "auto",
            "failurePolicy": "fail-fast",
        }
    if not isinstance(raw_defaults, Mapping):
        _fail("workflow.defaults must be an object")
    _require_keys(
        raw_defaults,
        "workflow.defaults",
        {"maxConcurrency", "providerConcurrency", "timeoutSeconds", "workspace", "failurePolicy"},
    )

    max_concurrency = raw_defaults.get("maxConcurrency", 2)
    if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or max_concurrency < 1:
        _fail("workflow.defaults.maxConcurrency must be a positive integer")

    provider_concurrency = raw_defaults.get("providerConcurrency", {})
    if provider_concurrency is None:
        provider_concurrency = {}
    if not isinstance(provider_concurrency, Mapping):
        _fail("workflow.defaults.providerConcurrency must be an object")
    normalized_provider_concurrency: dict[str, int] = {}
    for provider, value in provider_concurrency.items():
        if not isinstance(provider, str) or not provider:
            _fail("workflow.defaults.providerConcurrency keys must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            _fail(
                f"workflow.defaults.providerConcurrency.{provider} must be a positive integer"
            )
        if provider not in registry_providers:
            _fail(f"workflow.defaults.providerConcurrency names unknown provider {provider!r}")
        normalized_provider_concurrency[provider] = value
    normalized_provider_concurrency = dict(sorted(normalized_provider_concurrency.items()))

    timeout_seconds = raw_defaults.get("timeoutSeconds", 1140)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        _fail("workflow.defaults.timeoutSeconds must be a positive number")

    workspace = raw_defaults.get("workspace", "auto")
    if workspace not in _WORKSPACES:
        _fail(f"workflow.defaults.workspace must be one of {sorted(_WORKSPACES)}")

    failure_policy = raw_defaults.get("failurePolicy", "fail-fast")
    if failure_policy not in _FAILURE_POLICIES:
        _fail(f"workflow.defaults.failurePolicy must be one of {sorted(_FAILURE_POLICIES)}")

    return {
        "maxConcurrency": max_concurrency,
        "providerConcurrency": normalized_provider_concurrency,
        "timeoutSeconds": timeout_seconds,
        "workspace": workspace,
        "failurePolicy": failure_policy,
    }


def validate_workflow(
    data: Any,
    *,
    source_path: Path,
    repo_root: Path,
    registry: Mapping[str, Any],
    host: str,
) -> tuple[dict[str, Any], list[str]]:
    """Validate and normalize a workflow document.

    ``source_path`` is the resolved path of the workflow JSON file; its parent
    directory anchors prompt file references. ``repo_root`` is accepted for
    API symmetry with ``load_registry`` but is not required for the current
    validation rules. Returns the normalized, deterministic workflow document
    plus a list of advisory warnings.
    """

    del repo_root  # currently unused; reserved for future contract checks

    warnings: list[str] = []

    if not isinstance(data, Mapping):
        _fail("workflow must be an object")

    if data.get("schemaVersion") != 1:
        _fail("workflow.schemaVersion must be 1")
    _require_keys(data, "workflow", {"schemaVersion", "name", "defaults", "tasks"})

    if host not in _HOSTS:
        _fail(f"workflow host must be one of {sorted(_HOSTS)}: {host!r}")

    name = data.get("name")
    if not isinstance(name, str) or not name:
        _fail("workflow.name must be a non-empty string")
    if len(name) > 128:
        _fail("workflow.name must be at most 128 characters")

    registry_providers = registry.get("providers", {}) if isinstance(registry, Mapping) else {}
    if not isinstance(registry_providers, Mapping):
        _fail("registry.providers must be an object")

    defaults = _normalize_defaults(data.get("defaults"), registry_providers)

    registry_hosts = registry.get("hosts", {}) if isinstance(registry, Mapping) else {}
    if not isinstance(registry_hosts, Mapping):
        _fail("registry.hosts must be an object")
    host_def = registry_hosts.get(host, {})
    native_providers: set[str] = set()
    if isinstance(host_def, Mapping):
        native = host_def.get("nativeProviders", [])
        if isinstance(native, list):
            native_providers = {entry for entry in native if isinstance(entry, str)}

    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, Mapping) or not raw_tasks:
        _fail("workflow.tasks must be a non-empty object")

    workflow_dir = source_path.parent

    task_names: set[str] = set()
    for task_name in raw_tasks:
        if not isinstance(task_name, str) or _TASK_NAME_PATTERN.fullmatch(task_name) is None:
            _fail(
                f"task name {task_name!r} must match [A-Za-z][A-Za-z0-9_-]{{0,63}}"
            )
        if task_name in task_names:
            _fail(f"workflow.tasks duplicates task name {task_name!r}")
        task_names.add(task_name)

    normalized_tasks: dict[str, dict[str, Any]] = {}
    for task_name in sorted(task_names):
        task_def = raw_tasks.get(task_name)
        normalized_tasks[task_name] = _normalize_task(
            task_name,
            task_def,
            defaults=defaults,
            workflow_dir=workflow_dir,
            registry_providers=registry_providers,
            native_providers=native_providers,
            host=host,
            warnings=warnings,
            task_names=task_names,
        )

    deps_for_cycle = {name: task["dependsOn"] for name, task in normalized_tasks.items()}
    cycle = _find_cycle(deps_for_cycle)
    if cycle:
        path_str = " -> ".join(cycle)
        _fail(f"dependency cycle detected: {path_str}")

    return (
        {
            "schemaVersion": 1,
            "name": name,
            "defaults": defaults,
            "tasks": normalized_tasks,
        },
        warnings,
    )


def load_workflow(
    path: Path,
    *,
    repo_root: Path,
    registry: Mapping[str, Any],
    host: str,
) -> dict[str, Any]:
    """Read, parse, validate, and normalize a workflow JSON document."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"cannot read workflow file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"workflow file {path} is not valid JSON: {exc}") from exc

    resolved = path.resolve()
    normalized, _warnings = validate_workflow(
        data,
        source_path=resolved,
        repo_root=repo_root,
        registry=registry,
        host=host,
    )
    return normalized


def workflow_digest(normalized: Mapping[str, Any]) -> str:
    """Return a deterministic lowercase SHA-256 of the normalized workflow."""

    canonical = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
