"""Load and semantically validate the canonical provider registry."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


class RegistryError(ValueError):
    """Raised when provider-registry data violates the runtime contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistryError(message)


def _require_string(value: Any, field: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{field} must be a non-empty string")
    return value


def _require_string_list(value: Any, field: str, *, min_items: int = 0) -> list[str]:
    _require(isinstance(value, list), f"{field} must be a list")
    _require(all(isinstance(item, str) and item for item in value), f"{field} must contain strings")
    _require(len(value) == len(set(value)), f"{field} must not contain duplicates")
    _require(len(value) >= min_items, f"{field} must contain at least {min_items} item(s)")
    return value


def _require_keys(value: dict[str, Any], field: str, required: set[str], optional: set[str] | None = None) -> None:
    allowed = required | (optional or set())
    missing = required - set(value)
    extra = set(value) - allowed
    _require(not missing, f"{field} is missing required fields: {', '.join(sorted(missing))}")
    _require(not extra, f"{field} has unknown fields: {', '.join(sorted(extra))}")


def _require_identifier(value: Any, field: str, *, pattern: str) -> str:
    identifier = _require_string(value, field)
    _require(re.fullmatch(pattern, identifier) is not None, f"{field} has invalid format: {identifier!r}")
    _require(".." not in identifier.split("/"), f"{field} must not contain a parent path segment")
    return identifier


def _repo_path(repo_root: Path, relative: str, field: str) -> Path:
    candidate = Path(relative)
    _require(not candidate.is_absolute(), f"{field} must be relative to the repository")
    root = repo_root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RegistryError(f"{field} escapes the repository: {relative}") from exc
    return resolved


def load_registry(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot load provider registry {path}: {exc}") from exc
    validate_registry(data, repo_root=path.resolve().parents[1])
    return data


def validate_registry(data: Any, *, repo_root: Path) -> None:
    _require(isinstance(data, dict), "registry must be an object")
    _require(data.get("schemaVersion") == 1, "registry schemaVersion must be 1")
    hosts = data.get("hosts")
    providers = data.get("providers")
    _require(bool(isinstance(hosts, dict) and hosts), "hosts must be a non-empty object")
    _require(bool(isinstance(providers, dict) and providers), "providers must be a non-empty object")
    _require("mythos" not in json.dumps(data).lower(), "registry must not define a Mythos-specific surface")
    _require_keys(data, "registry", {"schemaVersion", "hosts", "providers"})

    for host_id, host in hosts.items():
        _require_identifier(host_id, "host id", pattern=r"[a-z0-9-]+")
        _require(isinstance(host, dict), f"host {host_id} must be an object")
        _require_keys(host, f"hosts.{host_id}", {"displayName", "packagePath", "nativeProviders"})
        _require_string(host.get("displayName"), f"hosts.{host_id}.displayName")
        package_path = _require_string(host.get("packagePath"), f"hosts.{host_id}.packagePath")
        _require(_repo_path(repo_root, package_path, f"hosts.{host_id}.packagePath").is_dir(), f"host {host_id} package does not exist: {package_path}")
        native = _require_string_list(host.get("nativeProviders"), f"hosts.{host_id}.nativeProviders")
        for provider_id in native:
            _require(provider_id in providers, f"host {host_id} names unknown native provider {provider_id}")

    aliases: dict[str, str] = {}
    shims: set[str] = set()
    for provider_id, provider in providers.items():
        _require_identifier(provider_id, "provider id", pattern=r"[a-z0-9-]+")
        _require(isinstance(provider, dict), f"provider {provider_id} must be an object")
        _require_keys(
            provider,
            f"providers.{provider_id}",
            {
                "displayName", "shim", "binaryCandidates", "nativeHosts", "promptDelivery",
                "allowUnknownModels", "defaultModel", "modelSelectors", "effort", "capabilities",
                "models", "routeFamilies",
            },
            {"binaryOverrideEnv"},
        )
        _require_string(provider.get("displayName"), f"providers.{provider_id}.displayName")
        shim = _require_string(provider.get("shim"), f"providers.{provider_id}.shim")
        _require(re.fullmatch(r"[a-z0-9-]+-shim\.sh", shim) is not None, f"provider {provider_id} has invalid shim name")
        _require(shim not in shims, f"shim {shim} is assigned to multiple providers")
        shims.add(shim)
        _require(_repo_path(repo_root, f"scripts/{shim}", f"providers.{provider_id}.shim").is_file(), f"provider {provider_id} shim does not exist: {shim}")
        _require_string_list(provider.get("binaryCandidates"), f"providers.{provider_id}.binaryCandidates", min_items=1)
        override = provider.get("binaryOverrideEnv")
        if override is not None:
            _require(
                isinstance(override, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", override) is not None,
                f"providers.{provider_id}.binaryOverrideEnv has invalid format",
            )
        native_hosts = _require_string_list(provider.get("nativeHosts"), f"providers.{provider_id}.nativeHosts")
        for host_id in native_hosts:
            _require(host_id in hosts, f"provider {provider_id} names unknown native host {host_id}")
            _require(
                provider_id in hosts[host_id]["nativeProviders"],
                f"provider {provider_id} and host {host_id} disagree about native ownership",
            )
        _require(provider.get("promptDelivery") in {"stdin", "argv"}, f"provider {provider_id} has invalid promptDelivery")
        _require(isinstance(provider.get("allowUnknownModels"), bool), f"provider {provider_id} allowUnknownModels must be boolean")
        _require_string_list(provider.get("modelSelectors"), f"providers.{provider_id}.modelSelectors")

        effort = provider.get("effort")
        _require(isinstance(effort, dict), f"provider {provider_id} effort must be an object")
        _require_keys(effort, f"providers.{provider_id}.effort", {"kind", "key", "values"})
        effort_kind = effort.get("kind")
        _require(effort_kind in {"config", "provider-flag", "none"}, f"provider {provider_id} has invalid effort kind")
        effort_values = _require_string_list(effort.get("values"), f"providers.{provider_id}.effort.values")
        if effort_kind == "none":
            _require(effort.get("key") is None, f"provider {provider_id} effort key must be null when kind is none")
            _require(not effort_values, f"provider {provider_id} effort values must be empty when kind is none")
        else:
            _require_string(effort.get("key"), f"providers.{provider_id}.effort.key")

        capabilities = provider.get("capabilities")
        _require(isinstance(capabilities, dict), f"provider {provider_id} capabilities must be an object")
        _require_keys(
            capabilities,
            f"providers.{provider_id}.capabilities",
            {"authProbe", "configProbe", "worktreeDispatch", "structuredOutput"},
        )
        for capability, enabled in capabilities.items():
            _require(isinstance(enabled, bool), f"providers.{provider_id}.capabilities.{capability} must be boolean")

        default_model = provider.get("defaultModel")
        _require(isinstance(default_model, dict), f"provider {provider_id} defaultModel must be an object")
        _require_keys(default_model, f"providers.{provider_id}.defaultModel", {"source", "fallback"})
        _require(
            default_model.get("source") in {"registry", "codex-config", "kimi-config", "positional"},
            f"provider {provider_id} has invalid default model source",
        )
        fallback = default_model.get("fallback")
        _require(fallback is None or isinstance(fallback, str), f"provider {provider_id} fallback must be string or null")
        if default_model.get("source") == "positional":
            _require(fallback is None, f"provider {provider_id} positional default must have a null fallback")

        models = provider.get("models")
        families = provider.get("routeFamilies")
        _require(isinstance(models, dict), f"provider {provider_id} models must be an object")
        _require(isinstance(families, list), f"provider {provider_id} routeFamilies must be a list")
        if default_model.get("source") == "registry":
            _require(fallback in models, f"provider {provider_id} registry fallback {fallback!r} is not a known model")

        for model_id, model in models.items():
            _require_identifier(model_id, f"providers.{provider_id}.model id", pattern=r"[A-Za-z0-9][A-Za-z0-9._/-]*")
            _require(isinstance(model, dict), f"model {provider_id}/{model_id} must be an object")
            _require_keys(
                model,
                f"providers.{provider_id}.models.{model_id}",
                {"displayName", "aliases", "effortValues", "promptReference", "runtimeReference", "capabilityCard", "provenance"},
            )
            _require_string(model.get("displayName"), f"providers.{provider_id}.models.{model_id}.displayName")
            _require_string(model.get("provenance"), f"providers.{provider_id}.models.{model_id}.provenance")
            _validate_reference_paths(model, repo_root, hosts, f"providers.{provider_id}.models.{model_id}")
            model_aliases = _require_string_list(model.get("aliases"), f"providers.{provider_id}.models.{model_id}.aliases")
            _require_string_list(model.get("effortValues"), f"providers.{provider_id}.models.{model_id}.effortValues")
            for alias in [model_id, *model_aliases]:
                owner = aliases.setdefault(alias.lower(), f"{provider_id}/{model_id}")
                _require(owner == f"{provider_id}/{model_id}", f"model alias {alias!r} is duplicated by {owner}")

        family_ids: set[str] = set()
        for family in families:
            _require(isinstance(family, dict), f"provider {provider_id} route family must be an object")
            _require_keys(
                family,
                f"providers.{provider_id}.routeFamilies",
                {"id", "displayName", "patterns", "example", "promptReference", "runtimeReference", "capabilityCard"},
            )
            family_id = _require_identifier(family.get("id"), f"providers.{provider_id}.routeFamilies.id", pattern=r"[a-z0-9-]+")
            _require(family_id not in family_ids, f"provider {provider_id} duplicates route family {family_id}")
            family_ids.add(family_id)
            _require_string(family.get("displayName"), f"providers.{provider_id}.routeFamilies.{family_id}.displayName")
            _require_string_list(family.get("patterns"), f"providers.{provider_id}.routeFamilies.{family_id}.patterns", min_items=1)
            _require_string(family.get("example"), f"providers.{provider_id}.routeFamilies.{family_id}.example")
            _validate_reference_paths(family, repo_root, hosts, f"providers.{provider_id}.routeFamilies.{family_id}")

    for host_id, host in hosts.items():
        for provider_id in host["nativeProviders"]:
            _require(
                host_id in providers[provider_id]["nativeHosts"],
                f"host {host_id} and provider {provider_id} disagree about native ownership",
            )

    from model_routing.providers import adapter_ids, get_adapter

    _require(set(providers) == adapter_ids(), "provider registry and adapter implementations must match")
    for provider_id, provider in providers.items():
        adapter = get_adapter(provider_id)
        _require(
            adapter.prompt_delivery == provider["promptDelivery"],
            f"provider {provider_id} registry and adapter disagree about prompt delivery",
        )
        _require(
            adapter.binary_override_env == provider.get("binaryOverrideEnv"),
            f"provider {provider_id} registry and adapter disagree about binary override",
        )


def _validate_reference_paths(
    item: dict[str, Any],
    repo_root: Path,
    hosts: dict[str, Any],
    field: str,
) -> None:
    for key in ("promptReference", "capabilityCard"):
        relative = _require_string(item.get(key), f"{field}.{key}")
        _require(_repo_path(repo_root, relative, f"{field}.{key}").is_file(), f"{field}.{key} does not exist: {relative}")
    runtime_reference = _require_string(item.get("runtimeReference"), f"{field}.runtimeReference")
    relative, separator, anchor = runtime_reference.partition("#")
    _require(relative == "references/model-prompting.md", f"{field}.runtimeReference must use package-local model-prompting.md")
    _require(bool(separator and anchor), f"{field}.runtimeReference must include an anchor")
    for host_id, host in hosts.items():
        bundle = _repo_path(
            repo_root,
            f"{host['packagePath']}/skills/subagent-model-routing/{relative}",
            f"hosts.{host_id}.runtimeReferenceBundle",
        )
        _require(bundle.is_file(), f"host {host_id} runtime reference bundle does not exist: {bundle}")
        contents = bundle.read_text(encoding="utf-8").lower()
        _require(f"(#{anchor.lower()})" in contents, f"{field}.runtimeReference anchor does not exist for host {host_id}: {anchor}")
