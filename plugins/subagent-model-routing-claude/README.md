# subagent-model-routing-claude

Claude Code package for routing work to **non-Claude models** (codex/GPT-5.x,
Grok 4.5, Kimi, GLM, MiniMax, and local/self-hosted models)
over the repo-installed codex/kimi/opencode/grok shims. The primary `subagent-model-routing` skill handles
**both** dispatch shapes; an internal §0 decision picks which:

- **Flat dispatch** — independent, one-shot units (no dependency edges). Direct `Agent`/`Bash` shim calls.
- **DAG orchestration** — dependency edges (A→B, fan-out you collect/order). The `Workflow` tool, nodes routed via `agentType`.

**Why one skill, not two:** flat-vs-DAG is a *branch over shared substrate*, not two separate tools. The model-picking logic, the roster, and the transport lore are needed by **both** paths, so they live **once, inline**, in-context for every task — no "referenced but not loaded" gap. (`/subagent-model-routing-claude:dag-routing` is the entry command; §0 down-routes a flat task to the flat half on its own.)

## Install and validate

From this repo checkout:

```bash
claude plugin marketplace add <repo> --scope user
claude plugin install subagent-model-routing-claude@subagent-model-routing --scope user
claude plugin details subagent-model-routing-claude@subagent-model-routing
claude plugin validate <repo>/plugins/subagent-model-routing-claude
```

## What's in the plugin

- `skills/subagent-model-routing/SKILL.md` — the whole thing: §0 router, shared model-picking, **Part A** (DAG orchestration), **Part B** (flat dispatch + shared transport substrate). Companion doc: `ARCHITECTURE.md` (DAG internals).
- `commands/dag-routing.md` — the `/subagent-model-routing-claude:dag-routing` entry command.
- `commands/distill.md` — the `/subagent-model-routing-claude:distill` ledger-promotion command.
- `agents/{codex,kimi,opencode,grok}-shim.md` — the Sonnet transport agent contracts.
- `hooks/` — the Stop-hook tripwire (flags a DAG run that leaked to direct dispatch). Disable via the plugin or `hooks/hooks.json`.

## Shared runtime prerequisite

The plugin package does not duplicate the executable runtime. From the repository root, run `scripts/install.sh` (or `scripts/bootstrap.sh`) before installing the plugin; that installs `model-routing` plus `codex-shim`, `kimi-shim`, `opencode-shim`, `grok-shim`, and `claude-shim` under `~/.claude/scripts/`. This Claude Code package actively routes through the first four; `claude-shim` is a target route for the Codex and Copilot packages, while Claude-hosted work uses native Claude `Agent` calls. Bootstrap can optionally install selected missing provider CLIs through its checkbox screen; `model-routing setup providers` reruns it later. Provider authentication remains separate, and the shared runtime requires Python 3.11+.

```bash
test -x ~/.claude/scripts/codex-shim.sh && test -x ~/.claude/scripts/kimi-shim.sh && test -x ~/.claude/scripts/opencode-shim.sh && test -x ~/.claude/scripts/grok-shim.sh && echo "shims present"
~/.claude/scripts/model-routing runs list
~/.claude/scripts/model-routing doctor
```

Active routes are GPT via `codex-shim`, Kimi via `kimi-shim`, Grok 4.5 via `grok-shim`, and GLM/MiniMax/local models via `opencode-shim`. The repo-installed shims log quantitative ledger records with `"source":"shim"` (`event`: `started`/`finished`) and emit a final `SHIM-DONE exit=<n>` sentinel per run.

Codex, Kimi, Grok, and OpenCode write dispatches can opt into `--routing-workspace isolated --routing-task-mode write`; review with `model-routing runs diff`, apply explicitly, and discard the retained worktree explicitly. Claude work remains native to Claude Code's Agent/Workflow surfaces.

Claude's native Workflow remains the default for Claude-hosted dependency graphs. The shared `model-routing workflow run workflow.json --host claude` command is available only for explicitly requested external-only Codex/Kimi/Grok/OpenCode graphs and does not replace `/dag-routing` or the tripwire hooks. The self-declared host value is advisory; observed Claude tool use remains the enforcement signal.

Model discovery is explicit with `model-routing doctor --discover-models`; the default doctor and dispatch preflight never run it.

**Tier example (seed — maintain via `/subagent-model-routing-claude:distill` and your own ledger):**
codex GPT-5.6 Sol (provisional flagship seat) ≥ GLM-5.2 (Opus peer, default author) > Kimi K2.7 > MiniMax-M3 (Sonnet peer); Grok 4.5, GPT-5.6 Terra/Luna, and local/self-hosted models remain unranked pending local evidence.

## Prompt references

The runtime skill includes compact prompt cards for its active codex/GPT, xAI/Grok, Kimi, GLM, MiniMax, and Qwen routes. Its self-contained detail is bundled at `skills/subagent-model-routing/references/model-prompting.md`, so it remains readable from an isolated plugin install. The Claude Code transport and system-card-grounded Claude Sonnet 5, Opus 4.8, and Fable 5 sections are route guidance for the Codex and Copilot packages; this Claude-hosted package keeps Claude work native. No Mythos-specific reference or route is defined. In a source checkout, the canonical authoring references live in the repo-level `prompting/` directory; start with `prompting/00-prompt-reference-index.md` when updating guidance. Local/self-hosted models (including Qwen) route through the `opencode-shim` custom-provider path; see the root README for an example.
