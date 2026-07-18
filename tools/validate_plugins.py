#!/usr/bin/env python3
"""Validate package structure and host-native routing boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "claude": ROOT / "plugins" / "subagent-model-routing-claude",
    "codex": ROOT / "plugins" / "subagent-model-routing-codex",
    "copilot": ROOT / "plugins" / "subagent-model-routing-copilot",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    manifests = {
        "claude": PACKAGES["claude"] / ".claude-plugin" / "plugin.json",
        "codex": PACKAGES["codex"] / ".codex-plugin" / "plugin.json",
        "copilot": PACKAGES["copilot"] / "plugin.json",
    }
    documents = {host: json.loads(path.read_text(encoding="utf-8")) for host, path in manifests.items()}
    require({document["version"] for document in documents.values()} == {"0.6.0"}, "plugin versions drifted")

    for host, package in PACKAGES.items():
        skill = package / "skills" / "subagent-model-routing" / "SKILL.md"
        readme = package / "README.md"
        require(skill.is_file() and readme.is_file(), f"{host}: required skill/README missing")
        skill_text = skill.read_text(encoding="utf-8")
        require(skill_text.startswith("---\n") and "\n---\n" in skill_text[4:], f"{host}: invalid skill frontmatter")
        readme_text = readme.read_text(encoding="utf-8")
        require("Shared runtime prerequisite" in readme_text, f"{host}: runtime prerequisite undocumented")
        require("plugin package does not duplicate" in readme_text, f"{host}: package boundary undocumented")
        require("scripts/install.sh" in readme_text, f"{host}: root installer undocumented")
        require(not (package / "scripts").exists(), f"{host}: runtime must remain single-sourced at repo root")

    claude_skill = (PACKAGES["claude"] / "skills/subagent-model-routing/SKILL.md").read_text(encoding="utf-8")
    codex_skill = (PACKAGES["codex"] / "skills/subagent-model-routing/SKILL.md").read_text(encoding="utf-8")
    copilot_skill = (PACKAGES["copilot"] / "skills/subagent-model-routing/SKILL.md").read_text(encoding="utf-8")
    require("~/.claude/scripts/claude-shim.sh" not in claude_skill, "Claude package routes its native provider")
    require("~/.claude/scripts/codex-shim.sh" not in codex_skill, "Codex package routes its native provider")
    require("~/.claude/scripts/kimi-shim.sh" in claude_skill, "Claude package lacks Kimi route")
    require("~/.claude/scripts/claude-shim.sh" in codex_skill, "Codex package lacks Claude route")
    require("~/.claude/scripts/kimi-shim.sh" in codex_skill, "Codex package lacks Kimi route")
    require("~/.claude/scripts/codex-shim.sh" in copilot_skill, "Copilot package lacks Codex route")
    require("~/.claude/scripts/claude-shim.sh" in copilot_skill, "Copilot package lacks Claude route")
    require("~/.claude/scripts/kimi-shim.sh" in copilot_skill, "Copilot package lacks Kimi route")

    mythos_paths = [
        path
        for root in (ROOT / "prompting", ROOT / "plugins")
        for path in root.rglob("*")
        if re.search("mythos", path.name, re.I)
    ]
    require(not mythos_paths, f"Mythos-specific surfaces are forbidden: {mythos_paths}")
    print("all plugin structures and host-native boundaries are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
