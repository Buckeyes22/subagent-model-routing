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

## Shared runtime prerequisite

The plugin package does not duplicate the executable runtime. From the repository root, run `scripts/install.sh` (or `scripts/bootstrap.sh`) before installing the plugin; that installs the Python 3.11+ shared runtime as `~/.claude/scripts/model-routing` plus `~/.claude/scripts/{codex,claude,kimi,opencode,grok}-shim.sh`.

Interactive bootstrap can optionally install any selected missing provider CLI through a checkbox screen; rerun it later with `~/.claude/scripts/model-routing setup providers`. Provider executables are still external dependencies, and authentication is never automated.

```bash
test -x ~/.claude/scripts/codex-shim.sh
test -x ~/.claude/scripts/claude-shim.sh
test -x ~/.claude/scripts/kimi-shim.sh
test -x ~/.claude/scripts/opencode-shim.sh
test -x ~/.claude/scripts/grok-shim.sh
~/.claude/scripts/model-routing runs list
~/.claude/scripts/model-routing doctor
```

The Copilot skill uses those shims from direct shell commands with prompt files.

Write dispatches through any shim can opt into `--routing-workspace isolated --routing-task-mode write`; review with `model-routing runs diff`, apply explicitly, and discard the retained worktree explicitly.

For a durable dependency graph across any of the five transports, use `model-routing workflow run workflow.json --host copilot`. The runner provides concurrency, explicit artifact handoff, retries, verification, cancellation, and resume. `--host` is advisory metadata rather than a security boundary.

Model discovery is explicit with `model-routing doctor --discover-models`; the default doctor and dispatch preflight never run it.

Active routes are GPT via `codex-shim`—including the current Codex runtime model IDs `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`—Claude models via `claude-shim` (Sonnet 5 as the default workhorse, Opus 4.8 for difficult or verification-heavy work, and Fable 5 for the hardest generally available Claude work), Kimi via `kimi-shim`, Grok 4.5 via `grok-shim`, and GLM/MiniMax/local models via `opencode-shim`. Fable's production safeguards may block or fall back in protected domains; this project defines no Mythos-specific route.

## Prompt References

The Copilot-compatible skill includes compact prompt cards for prompt files sent through the Codex, Claude Code, Grok, OpenCode-provider, and local-model routes, with self-contained detail at `skills/subagent-model-routing/references/model-prompting.md` for isolated plugin installs. In a source checkout, canonical authoring references under `prompting/` include separate system-card-grounded guides for Claude Sonnet 5, Opus 4.8, and Fable 5; start with `prompting/00-prompt-reference-index.md` before updating runtime cards or the bundled compilation. Local/self-hosted models (including Qwen) route through the `opencode-shim` custom-provider path; see the root README for an example.
