# subagent-model-routing-codex

Codex-native companion package for the Claude Code `subagent-model-routing-claude` plugin.

This package is intentionally separate from `plugins/subagent-model-routing-claude/` so Codex does not load Claude-only plugin surfaces such as Claude hook files, agent markdown definitions, slash commands, or Workflow instructions.

## What It Contains

- `.codex-plugin/plugin.json` - Codex plugin manifest.
- `skills/subagent-model-routing/SKILL.md` - Codex-native subagent-model-routing workflow.

## Install and validate

From this repo checkout:

```bash
codex plugin marketplace add <repo>
codex plugin add subagent-model-routing-codex@subagent-model-routing-local
codex plugin marketplace list
codex plugin list
python3 -m json.tool <repo>/plugins/subagent-model-routing-codex/.codex-plugin/plugin.json >/dev/null
```

Codex installs local plugins into its cache under
`~/.codex/plugins/cache/subagent-model-routing-local/subagent-model-routing-codex/<version>/`.
Restart Codex or start a new thread after reinstalling so the updated skill is
loaded.

## What It Does Not Contain

- No Claude Code `.claude-plugin` manifest.
- No Claude Code `agents/*.md` transport subagents.
- No Claude Code `commands/*.md` slash command.
- No lifecycle hook package. The Claude Stop hook depends on Claude transcript fields and environment variables, so it stays in the Claude package only.

## Shared runtime prerequisite

The plugin package does not duplicate the executable runtime. From the repository root, run `scripts/install.sh` (or `scripts/bootstrap.sh`) before installing the plugin; that installs the Python 3.11+ shared runtime as `~/.claude/scripts/model-routing` plus `{codex,claude,kimi,opencode,grok}-shim.sh`. The Codex-native package targets only the external Claude, Kimi, Grok, and OpenCode harnesses; it does not route Codex back through its own CLI.

Interactive bootstrap can optionally install any selected missing provider CLI through a checkbox screen; rerun it later with `~/.claude/scripts/model-routing setup providers`. Provider executables are still external dependencies, and authentication is never automated.

```bash
test -x ~/.claude/scripts/claude-shim.sh
test -x ~/.claude/scripts/kimi-shim.sh
test -x ~/.claude/scripts/opencode-shim.sh
test -x ~/.claude/scripts/grok-shim.sh
~/.claude/scripts/model-routing runs list
~/.claude/scripts/model-routing doctor
```

The Codex skill uses those shims from direct shell commands with prompt files.

External write dispatches can opt into `--routing-workspace isolated --routing-task-mode write`; review them with `model-routing runs diff`, apply explicitly, and discard the retained worktree explicitly. Codex work itself stays native and inline.

For a durable external-only dependency graph, use `model-routing workflow run workflow.json --host codex`. The validator rejects Codex transport tasks, while Claude/Kimi/Grok/OpenCode tasks can use concurrency, explicit artifact handoff, retries, verification, cancellation, and resume. `--host` is advisory metadata; the package's native-family rule remains part of the routing contract.

Model discovery is explicit with `model-routing doctor --discover-models`; the default doctor and dispatch preflight never run it.

Active routes are Claude models via `claude-shim` (Sonnet 5 as the default workhorse, Opus 4.8 for difficult or verification-heavy work, and Fable 5 for the hardest generally available Claude work, plus `haiku` and full-name overrides), Kimi via `kimi-shim`, Grok 4.5 via `grok-shim`, and GLM/MiniMax/local models via `opencode-shim`. Fable's production safeguards may block or fall back in protected domains; this project defines no Mythos-specific route. Codex work stays native in the current thread.

## Prompt References

The Codex-native skill includes compact prompt cards for its Claude Code, Grok, OpenCode-provider, and local-model routes, with self-contained detail at `skills/subagent-model-routing/references/model-prompting.md` for isolated plugin installs. In a source checkout, canonical authoring references under `prompting/` include separate system-card-grounded guides for Claude Sonnet 5, Opus 4.8, and Fable 5; start with `prompting/00-prompt-reference-index.md` before updating runtime cards or the bundled compilation. Local/self-hosted models (including Qwen) route through the `opencode-shim` custom-provider path; see the root README for an example.
