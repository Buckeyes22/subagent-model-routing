"""Tests for the Phase 6 workflow loader, validator, and digest."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.workflow import (  # noqa: E402
    WorkflowError,
    load_workflow,
    validate_workflow,
    workflow_digest,
)


def make_registry(*, hosts=None, providers=None):
    """Build a synthetic provider-registry dict for unit tests."""
    hosts_dict = {
        "claude": {"displayName": "Claude", "packagePath": "plugins/subagent-model-routing-claude", "nativeProviders": ["claude"]},
        "codex": {"displayName": "Codex", "packagePath": "plugins/subagent-model-routing-codex", "nativeProviders": ["codex"]},
        "copilot": {"displayName": "Copilot", "packagePath": "plugins/subagent-model-routing-copilot", "nativeProviders": []},
    }
    if hosts is not None:
        hosts_dict.update(hosts)
    providers_dict = {
        "claude": {
            "displayName": "Anthropic Claude Code",
            "shim": "claude-shim.sh",
            "binaryCandidates": ["claude"],
            "nativeHosts": ["claude"],
            "promptDelivery": "stdin",
            "allowUnknownModels": False,
            "defaultModel": {"source": "registry", "fallback": "sonnet"},
            "modelSelectors": ["sonnet"],
            "effort": {"kind": "provider-flag", "key": "--effort", "values": ["low", "medium", "high"]},
            "capabilities": {"authProbe": True, "worktreeDispatch": True, "structuredOutput": True},
            "models": {
                "sonnet": {
                    "displayName": "Claude Sonnet 5",
                    "aliases": ["SONNET-5", "ClaudeSonnet"],
                    "effortValues": ["low", "medium", "high"],
                    "promptReference": "prompting/anthropic-claude-sonnet-5-prompting-reference.md",
                    "runtimeReference": "references/model-prompting.md#claude-sonnet-5",
                    "capabilityCard": "plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger/claude-sonnet-5.md",
                    "provenance": "anthropic",
                },
                "opus": {
                    "displayName": "Claude Opus 4.8",
                    "aliases": [],
                    "effortValues": ["low", "medium", "high"],
                    "promptReference": "prompting/anthropic-claude-opus-4.8-prompting-reference.md",
                    "runtimeReference": "references/model-prompting.md#claude-opus-4.8",
                    "capabilityCard": "plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger/claude-opus-4.8.md",
                    "provenance": "anthropic",
                },
            },
            "routeFamilies": [],
        },
        "codex": {
            "displayName": "OpenAI Codex CLI",
            "shim": "codex-shim.sh",
            "binaryCandidates": ["codex"],
            "nativeHosts": ["codex"],
            "promptDelivery": "stdin",
            "allowUnknownModels": False,
            "defaultModel": {"source": "registry", "fallback": "gpt-5.6-sol"},
            "modelSelectors": ["gpt-5.6-sol"],
            "effort": {"kind": "config", "key": "model_reasoning_effort", "values": ["low", "medium", "high"]},
            "capabilities": {"authProbe": True, "worktreeDispatch": True, "structuredOutput": True},
            "models": {
                "gpt-5.6-sol": {
                    "displayName": "GPT-5.6-Sol",
                    "aliases": ["SOL"],
                    "effortValues": ["low", "medium", "high"],
                    "promptReference": "prompting/openai-codex-gpt-prompting-reference.md",
                    "runtimeReference": "references/model-prompting.md#gpt-5.6",
                    "capabilityCard": "plugins/subagent-model-routing-codex/skills/subagent-model-routing/ledger/codex.md",
                    "provenance": "openai",
                },
            },
            "routeFamilies": [],
        },
        "opencode": {
            "displayName": "OpenCode CLI",
            "shim": "opencode-shim.sh",
            "binaryCandidates": ["opencode"],
            "nativeHosts": [],
            "promptDelivery": "argv",
            "allowUnknownModels": True,
            "defaultModel": {"source": "positional", "fallback": None},
            "modelSelectors": [],
            "effort": {"kind": "provider-flag", "key": "--effort", "values": ["low", "medium"]},
            "capabilities": {"authProbe": False, "worktreeDispatch": True, "structuredOutput": True},
            "models": {},
            "routeFamilies": [],
        },
        "grok": {
            "displayName": "xAI Grok",
            "shim": "grok-shim.sh",
            "binaryCandidates": ["grok"],
            "nativeHosts": [],
            "promptDelivery": "stdin",
            "allowUnknownModels": True,
            "defaultModel": {"source": "positional", "fallback": None},
            "modelSelectors": [],
            "effort": {"kind": "provider-flag", "key": "--effort", "values": []},
            "capabilities": {"authProbe": False, "worktreeDispatch": True, "structuredOutput": True},
            "models": {},
            "routeFamilies": [],
        },
        "kimi": {
            "displayName": "Moonshot Kimi Code",
            "shim": "kimi-shim.sh",
            "binaryCandidates": ["kimi"],
            "nativeHosts": [],
            "promptDelivery": "argv",
            "allowUnknownModels": True,
            "defaultModel": {"source": "kimi-config", "fallback": "kimi-default"},
            "modelSelectors": ["-m", "--model"],
            "effort": {"kind": "provider-flag", "key": "--model", "values": []},
            "capabilities": {"authProbe": False, "worktreeDispatch": True, "structuredOutput": False},
            "models": {},
            "routeFamilies": [],
        },
    }
    if providers is not None:
        providers_dict.update(providers)
    return {
        "schemaVersion": 1,
        "hosts": hosts_dict,
        "providers": providers_dict,
    }


def write_workflow(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def minimal_task(**overrides):
    task = {
        "route": {"provider": "grok", "model": "grok-4.5"},
        "mode": "read",
        "prompt": {"text": "hello"},
    }
    task.update(overrides)
    return task


def validate(body, *, tmp_path, registry=None, host="copilot", source_name="workflow.json"):
    registry = registry if registry is not None else make_registry()
    source = write_workflow(tmp_path, source_name, body)
    return validate_workflow(
        body,
        source_path=source.resolve(),
        repo_root=tmp_path,
        registry=registry,
        host=host,
    )


class LoadWorkflowTests(unittest.TestCase):
    def test_load_minimal_workflow(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            body = {
                "schemaVersion": 1,
                "name": "smoke",
                "tasks": {"one": minimal_task()},
            }
            path = write_workflow(tmp_path, "workflow.json", body)
            normalized = load_workflow(
                path, repo_root=tmp_path, registry=make_registry(), host="copilot"
            )
            self.assertEqual(normalized["schemaVersion"], 1)
            self.assertEqual(normalized["name"], "smoke")
            self.assertEqual(normalized["defaults"]["maxConcurrency"], 2)
            self.assertEqual(normalized["defaults"]["failurePolicy"], "fail-fast")
            self.assertIn("one", normalized["tasks"])

    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                load_workflow(
                    tmp_path / "missing.json",
                    repo_root=tmp_path,
                    registry=make_registry(),
                    host="copilot",
                )

    def test_load_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            path = tmp_path / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(WorkflowError):
                load_workflow(
                    path, repo_root=tmp_path, registry=make_registry(), host="copilot"
                )


class SchemaAndNameTests(unittest.TestCase):
    def test_schema_version_required(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate({"schemaVersion": 2, "name": "x", "tasks": {"a": minimal_task()}}, tmp_path=tmp_path)

    def test_schema_version_missing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate({"name": "x", "tasks": {"a": minimal_task()}}, tmp_path=tmp_path)

    def test_name_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate({"schemaVersion": 1, "name": "", "tasks": {"a": minimal_task()}}, tmp_path=tmp_path)

    def test_name_too_long(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {"schemaVersion": 1, "name": "x" * 129, "tasks": {"a": minimal_task()}},
                    tmp_path=tmp_path,
                )

    def test_unknown_top_level_key(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task()},
                        "bogus": True,
                    },
                    tmp_path=tmp_path,
                )

    def test_boolean_integer_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            bodies = [
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "defaults": {"maxConcurrency": True},
                    "tasks": {"a": minimal_task()},
                },
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "defaults": {"providerConcurrency": {"grok": True}},
                    "tasks": {"a": minimal_task()},
                },
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {"a": minimal_task(retry={"maxAttempts": True})},
                },
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(),
                        "b": minimal_task(
                            dependsOn=["a"],
                            contextFrom=[
                                {"task": "a", "artifact": "stdout", "maxBytes": True}
                            ],
                        ),
                    },
                },
            ]
            for body in bodies:
                with self.subTest(body=body), self.assertRaises(WorkflowError):
                    validate(body, tmp_path=tmp_path)


class HostAndRouteTests(unittest.TestCase):
    def test_invalid_host(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {"schemaVersion": 1, "name": "x", "tasks": {"a": minimal_task()}},
                    tmp_path=tmp_path,
                    host="windsurf",
                )

    def test_native_claude_provider_rejected_on_claude_host(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(route={"provider": "claude", "model": "sonnet"})
                        },
                    },
                    tmp_path=tmp_path,
                    host="claude",
                )

    def test_native_codex_provider_rejected_on_codex_host(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                route={"provider": "codex", "model": "gpt-5.6-sol"}
                            )
                        },
                    },
                    tmp_path=tmp_path,
                    host="codex",
                )

    def test_copilot_permits_all_providers(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _warnings = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(route={"provider": "claude", "model": "sonnet"}),
                        "b": minimal_task(route={"provider": "codex", "model": "gpt-5.6-sol"}),
                        "c": minimal_task(route={"provider": "grok", "model": "grok-4.5"}),
                        "d": minimal_task(route={"provider": "kimi", "model": "kimi-code/kimi-for-coding"}),
                        "e": minimal_task(route={"provider": "opencode", "model": "custom/model"}),
                    },
                },
                tmp_path=tmp_path,
                host="copilot",
            )
            self.assertEqual(set(normalized["tasks"]), {"a", "b", "c", "d", "e"})

    def test_claude_provider_accepted_on_codex_host(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _warnings = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(route={"provider": "claude", "model": "sonnet"})
                    },
                },
                tmp_path=tmp_path,
                host="codex",
            )
            self.assertEqual(normalized["tasks"]["a"]["route"]["provider"], "claude")

    def test_unknown_provider_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task(route={"provider": "mystery", "model": "x"})},
                    },
                    tmp_path=tmp_path,
                )

    def test_alias_resolved_case_insensitively(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _warnings = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(
                            route={"provider": "claude", "model": "SONNET-5"},
                            mode="read",
                        )
                    },
                },
                tmp_path=tmp_path,
                host="codex",
            )
            self.assertEqual(normalized["tasks"]["a"]["route"]["model"], "sonnet")

    def test_unknown_model_allowed_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, warnings = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(
                            route={"provider": "grok", "model": "future-grok-7"},
                        )
                    },
                },
                tmp_path=tmp_path,
                host="copilot",
            )
            self.assertEqual(normalized["tasks"]["a"]["route"]["model"], "future-grok-7")
            self.assertTrue(any("not declared" in w for w in warnings))

    def test_unknown_model_rejected_when_disallowed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                route={"provider": "codex", "model": "future-gpt-9"},
                            )
                        },
                    },
                    tmp_path=tmp_path,
                    host="copilot",
                )

    def test_effort_not_allowed_by_provider(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                route={
                                    "provider": "grok",
                                    "model": "grok-4.5",
                                    "effort": "low",
                                }
                            )
                        },
                    },
                    tmp_path=tmp_path,
                    host="copilot",
                )

    def test_effort_rejected_by_model_effort_values(self):
        registry = make_registry(
            providers={
                "codex": {
                    "displayName": "OpenAI Codex CLI",
                    "shim": "codex-shim.sh",
                    "binaryCandidates": ["codex"],
                    "nativeHosts": ["codex"],
                    "promptDelivery": "stdin",
                    "allowUnknownModels": False,
                    "defaultModel": {"source": "registry", "fallback": "gpt-5.6-sol"},
                    "modelSelectors": [],
                    "effort": {
                        "kind": "config",
                        "key": "model_reasoning_effort",
                        "values": ["low", "medium", "high", "xhigh"],
                    },
                    "capabilities": {
                        "authProbe": True,
                        "worktreeDispatch": True,
                        "structuredOutput": True,
                    },
                    "models": {
                        "gpt-5.6-sol": {
                            "displayName": "GPT-5.6-Sol",
                            "aliases": [],
                            "effortValues": ["low", "medium"],
                            "promptReference": "prompting/openai-codex-gpt-prompting-reference.md",
                            "runtimeReference": "references/model-prompting.md#gpt-5.6",
                            "capabilityCard": "x",
                            "provenance": "openai",
                        }
                    },
                    "routeFamilies": [],
                }
            }
        )
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                route={
                                    "provider": "codex",
                                    "model": "gpt-5.6-sol",
                                    "effort": "xhigh",
                                }
                            )
                        },
                    },
                    tmp_path=tmp_path,
                    registry=registry,
                    host="codex",
                )


class TaskNameAndShapeTests(unittest.TestCase):
    def test_empty_tasks_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate({"schemaVersion": 1, "name": "x", "tasks": {}}, tmp_path=tmp_path)

    def test_task_name_starts_with_digit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"1bad": minimal_task()},
                    },
                    tmp_path=tmp_path,
                )

    def test_task_name_too_long(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a" * 65: minimal_task()},
                    },
                    tmp_path=tmp_path,
                )

    def test_task_name_boundary_lengths(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {"a": minimal_task(), "b" * 64: minimal_task()},
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(set(normalized["tasks"]), {"a", "b" * 64})

    def test_unknown_task_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": {**minimal_task(), "extra": True}},
                    },
                    tmp_path=tmp_path,
                )

    def test_mode_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task(mode="observe")},
                    },
                    tmp_path=tmp_path,
                )


class PromptTests(unittest.TestCase):
    def test_prompt_with_both_file_and_text(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            (tmp_path / "p.md").write_text("hi", encoding="utf-8")
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(prompt={"file": "p.md", "text": "hi"})
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_prompt_missing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": {**minimal_task(), "prompt": {}}},
                    },
                    tmp_path=tmp_path,
                )

    def test_prompt_inline_text_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task(prompt={"text": ""})},
                    },
                    tmp_path=tmp_path,
                )

    def test_prompt_file_absolute_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            absolute = tmp_path / "p.md"
            absolute.write_text("hi", encoding="utf-8")
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(prompt={"file": str(absolute)})
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_prompt_file_parent_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            outside = tmp_path.parent / "evil.md"
            outside.write_text("hi", encoding="utf-8")
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(prompt={"file": "../evil.md"})
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_prompt_file_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            outside_dir = tmp_path.parent
            outside_target = outside_dir / "outside.md"
            outside_target.write_text("hi", encoding="utf-8")
            link = tmp_path / "link.md"
            os.symlink(outside_target, link)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task(prompt={"file": "link.md"})},
                    },
                    tmp_path=tmp_path,
                )

    def test_prompt_file_resolves_to_regular_file(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            subdir = tmp_path / "prompts"
            subdir.mkdir()
            (subdir / "p.md").write_text("hi", encoding="utf-8")
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {"a": minimal_task(prompt={"file": "prompts/p.md"})},
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["a"]["prompt"], {"file": "prompts/p.md"})

    def test_prompt_file_missing_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(prompt={"file": "missing.md"})
                        },
                    },
                    tmp_path=tmp_path,
                )


class DependencyTests(unittest.TestCase):
    def test_missing_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(dependsOn=["missing"]),
                            "b": minimal_task(),
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_self_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task(dependsOn=["a"])},
                    },
                    tmp_path=tmp_path,
                )

    def test_duplicate_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(),
                            "b": minimal_task(dependsOn=["a", "a"]),
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_cycle_detected_with_path(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError) as ctx:
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(dependsOn=["c"]),
                            "b": minimal_task(dependsOn=["a"]),
                            "c": minimal_task(dependsOn=["b"]),
                        },
                    },
                    tmp_path=tmp_path,
                )
            self.assertIn("cycle", str(ctx.exception).lower())

    def test_depends_on_dedup_and_sort(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(),
                        "b": minimal_task(),
                        "c": minimal_task(dependsOn=["b", "a"]),
                    },
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["c"]["dependsOn"], ["a", "b"])


class ContextFromTests(unittest.TestCase):
    def test_context_from_indirect_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(),
                            "b": minimal_task(dependsOn=["a"]),
                            "c": minimal_task(
                                dependsOn=["b"],
                                contextFrom=[{"task": "a", "artifact": "stdout"}],
                            ),
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_context_from_invalid_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(),
                            "b": minimal_task(
                                dependsOn=["a"],
                                contextFrom=[{"task": "a", "artifact": "bogus"}],
                            ),
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_context_from_extra_keys_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(),
                            "b": minimal_task(
                                dependsOn=["a"],
                                contextFrom=[
                                    {"task": "a", "artifact": "stdout", "shell": True}
                                ],
                            ),
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_context_from_default_max_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(),
                        "b": minimal_task(
                            dependsOn=["a"],
                            contextFrom=[{"task": "a", "artifact": "stdout"}],
                        ),
                    },
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["b"]["contextFrom"][0]["maxBytes"], 50000)

    def test_context_from_negative_max_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(),
                            "b": minimal_task(
                                dependsOn=["a"],
                                contextFrom=[
                                    {"task": "a", "artifact": "stdout", "maxBytes": -1}
                                ],
                            ),
                        },
                    },
                    tmp_path=tmp_path,
                )


class TimeoutAndRetryTests(unittest.TestCase):
    def test_negative_task_timeout_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(timeoutSeconds=-1)
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_zero_task_timeout_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(timeoutSeconds=0)
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_retry_max_attempts_zero_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                retry={"maxAttempts": 0, "backoffSeconds": 0, "on": []}
                            )
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_retry_negative_backoff_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                retry={
                                    "maxAttempts": 1,
                                    "backoffSeconds": -0.5,
                                    "on": [],
                                }
                            )
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_retry_invalid_trigger_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                retry={
                                    "maxAttempts": 2,
                                    "backoffSeconds": 0,
                                    "on": ["quality"],
                                }
                            )
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_retry_duplicate_trigger_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(
                                retry={
                                    "maxAttempts": 2,
                                    "backoffSeconds": 0,
                                    "on": ["timeout", "timeout"],
                                }
                            )
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_retry_defaults_applied(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {"schemaVersion": 1, "name": "x", "tasks": {"a": minimal_task()}},
                tmp_path=tmp_path,
            )
            self.assertEqual(
                normalized["tasks"]["a"]["retry"],
                {"maxAttempts": 1, "backoffSeconds": 0, "on": []},
            )

    def test_inherited_task_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "defaults": {"timeoutSeconds": 60},
                    "tasks": {"a": minimal_task()},
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["a"]["timeoutSeconds"], 60)


class WorkspaceAndConcurrencyTests(unittest.TestCase):
    def test_concurrency_below_one_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "defaults": {"maxConcurrency": 0},
                        "tasks": {"a": minimal_task()},
                    },
                    tmp_path=tmp_path,
                )

    def test_concurrency_zero_provider_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "defaults": {"providerConcurrency": {"grok": 0}},
                        "tasks": {"a": minimal_task()},
                    },
                    tmp_path=tmp_path,
                )

    def test_write_task_with_shared_workspace_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(mode="write", workspace="shared")
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_write_task_with_isolated_workspace_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(mode="write", workspace="isolated")
                    },
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["a"]["workspace"], "isolated")

    def test_write_task_with_auto_workspace_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {"a": minimal_task(mode="write", workspace="auto")},
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["a"]["workspace"], "auto")

    def test_read_task_with_shared_workspace_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {"a": minimal_task(mode="read", workspace="shared")},
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["a"]["workspace"], "shared")

    def test_inherited_workspace_from_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "defaults": {"workspace": "isolated"},
                    "tasks": {"a": minimal_task()},
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["a"]["workspace"], "isolated")

    def test_invalid_workspace_enum_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {
                            "a": minimal_task(mode="read", workspace="unknown")
                        },
                    },
                    tmp_path=tmp_path,
                )

    def test_invalid_failure_policy_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "defaults": {"failurePolicy": "explode"},
                        "tasks": {"a": minimal_task()},
                    },
                    tmp_path=tmp_path,
                )


class VerifyTests(unittest.TestCase):
    def test_verify_argv_order_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(
                            verify=[
                                ["pytest", "-q", "tests/"],
                                ["ruff", "check", "--fix", "."],
                            ]
                        )
                    },
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(
                normalized["tasks"]["a"]["verify"],
                [["pytest", "-q", "tests/"], ["ruff", "check", "--fix", "."]],
            )

    def test_verify_empty_command_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task(verify=[[]])},
                    },
                    tmp_path=tmp_path,
                )

    def test_verify_empty_string_arg_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with self.assertRaises(WorkflowError):
                validate(
                    {
                        "schemaVersion": 1,
                        "name": "x",
                        "tasks": {"a": minimal_task(verify=[["pytest", ""]])},
                    },
                    tmp_path=tmp_path,
                )

    def test_verify_defaults_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {"schemaVersion": 1, "name": "x", "tasks": {"a": minimal_task()}},
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["a"]["verify"], [])


class NormalizationTests(unittest.TestCase):
    def test_defaults_applied(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {"schemaVersion": 1, "name": "x", "tasks": {"a": minimal_task()}},
                tmp_path=tmp_path,
            )
            self.assertEqual(
                normalized["defaults"],
                {
                    "maxConcurrency": 2,
                    "providerConcurrency": {},
                    "timeoutSeconds": 1140,
                    "workspace": "auto",
                    "failurePolicy": "fail-fast",
                },
            )

    def test_defaults_sorted_provider_concurrency(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "defaults": {
                        "providerConcurrency": {"grok": 3, "codex": 1, "claude": 2}
                    },
                    "tasks": {"a": minimal_task()},
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(
                list(normalized["defaults"]["providerConcurrency"].keys()),
                ["claude", "codex", "grok"],
            )

    def test_task_sort_order_in_output(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "zeta": minimal_task(),
                        "alpha": minimal_task(),
                        "mu": minimal_task(),
                    },
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(list(normalized["tasks"].keys()), ["alpha", "mu", "zeta"])

    def test_route_keys_sorted(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(
                            route={
                                "provider": "claude",
                                "model": "sonnet",
                                "effort": "high",
                            }
                        )
                    },
                },
                tmp_path=tmp_path,
                host="codex",
            )
            self.assertEqual(
                list(normalized["tasks"]["a"]["route"].keys()),
                ["effort", "model", "provider"],
            )

    def test_depends_on_sorted_unique(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(),
                        "b": minimal_task(),
                        "c": minimal_task(),
                        "d": minimal_task(dependsOn=["c", "a", "b"]),
                    },
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(normalized["tasks"]["d"]["dependsOn"], ["a", "b", "c"])


class DigestTests(unittest.TestCase):
    def test_digest_is_lowercase_sha256_hex(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            normalized, _ = validate(
                {"schemaVersion": 1, "name": "x", "tasks": {"a": minimal_task()}},
                tmp_path=tmp_path,
            )
            digest = workflow_digest(normalized)
            self.assertEqual(len(digest), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in digest))
            expected = hashlib.sha256(
                json.dumps(
                    normalized,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(digest, expected)

    def test_digest_is_key_order_independent(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            a, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "a": minimal_task(),
                        "b": minimal_task(),
                    },
                },
                tmp_path=tmp_path,
            )
            b, _ = validate(
                {
                    "schemaVersion": 1,
                    "name": "x",
                    "tasks": {
                        "b": minimal_task(),
                        "a": minimal_task(),
                    },
                },
                tmp_path=tmp_path,
            )
            self.assertEqual(workflow_digest(a), workflow_digest(b))

    def test_digest_changes_with_content(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            a, _ = validate(
                {"schemaVersion": 1, "name": "x", "tasks": {"a": minimal_task()}},
                tmp_path=tmp_path,
            )
            b, _ = validate(
                {"schemaVersion": 1, "name": "y", "tasks": {"a": minimal_task()}},
                tmp_path=tmp_path,
            )
            self.assertNotEqual(workflow_digest(a), workflow_digest(b))


class FullExampleTests(unittest.TestCase):
    def test_plan_example_normalizes_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            prompts = tmp_path / "prompts"
            prompts.mkdir()
            for name in ("analyze.md", "implement.md", "review.md"):
                (prompts / name).write_text(f"{name}\n", encoding="utf-8")
            body = {
                "schemaVersion": 1,
                "name": "cross-model-review",
                "defaults": {
                    "maxConcurrency": 2,
                    "timeoutSeconds": 1140,
                    "workspace": "auto",
                    "failurePolicy": "fail-fast",
                },
                "tasks": {
                    "analyze": {
                        "route": {"provider": "codex", "model": "gpt-5.6-sol", "effort": "high"},
                        "mode": "read",
                        "prompt": {"file": "prompts/analyze.md"},
                    },
                    "implement": {
                        "route": {"provider": "claude", "model": "sonnet", "effort": "high"},
                        "mode": "write",
                        "dependsOn": ["analyze"],
                        "contextFrom": [
                            {"task": "analyze", "artifact": "stdout", "maxBytes": 50000}
                        ],
                        "prompt": {"file": "prompts/implement.md"},
                    },
                    "review": {
                        "route": {"provider": "grok", "model": "grok-4.5"},
                        "mode": "read",
                        "dependsOn": ["implement"],
                        "contextFrom": [{"task": "implement", "artifact": "result"}],
                        "prompt": {"file": "prompts/review.md"},
                    },
                },
            }
            normalized, _warnings = validate(body, tmp_path=tmp_path, host="copilot")
            self.assertEqual(set(normalized["tasks"]), {"analyze", "implement", "review"})
            self.assertEqual(normalized["tasks"]["implement"]["dependsOn"], ["analyze"])
            self.assertEqual(
                normalized["tasks"]["implement"]["contextFrom"][0]["artifact"], "stdout"
            )
            digest = workflow_digest(normalized)
            self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
