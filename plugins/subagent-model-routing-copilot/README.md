# subagent-model-routing-copilot

Copilot-compatible companion package for the Claude Code `subagent-model-routing-claude`
plugin.

This package is intentionally separate from `plugins/subagent-model-routing-claude/` so
Copilot does not load Claude-only plugin surfaces such as Claude hook files,
agent markdown definitions, slash commands, or Workflow instructions. It is also
separate from `plugins/subagent-model-routing-codex/` so Copilot UI does not display
Codex-specific package metadata.

## What It Contains

- `plugin.json` - Copilot CLI / VS Code agent-plugin manifest.
- `skills/subagent-model-routing/SKILL.md` - Copilot-compatible subagent-model-routing workflow.

## What It Does Not Contain

- No Claude Code `.claude-plugin` manifest.
- No Codex `.codex-plugin` manifest.
- No Claude Code `agents/*.md` transport subagents.
- No Claude Code `commands/*.md` slash command.
- No lifecycle hook package. The Claude Stop hook depends on Claude transcript fields and environment variables, so it stays in the Claude package only.

## Shims (bundled)

The shim scripts are bundled under `scripts/` and installed onto `~/.claude/scripts/{codex,opencode}-shim.sh` by `scripts/install.sh`.

```bash
test -x ~/.claude/scripts/codex-shim.sh
test -x ~/.claude/scripts/opencode-shim.sh
```

The Copilot skill uses those shims from direct shell commands with prompt files.

Active routes are GPT via `codex-shim` and Kimi/GLM/MiniMax/local models via `opencode-shim`.

## Prompt References

The Copilot-compatible skill includes compact prompt cards for prompt files sent through the local shims. The full model-specific references live under `prompting/`; start with `prompting/00-prompt-reference-index.md` before updating runtime cards. Local/self-hosted models (including Qwen) route through the `opencode-shim` custom-provider path; see the root README for an example.
