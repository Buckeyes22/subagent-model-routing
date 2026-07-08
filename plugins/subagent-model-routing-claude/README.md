# subagent-model-routing-claude

Claude Code package for routing work to **non-Claude models** (codex/GPT-5.x,
Kimi, GLM, MiniMax, and local/self-hosted models via opencode custom providers)
over the bundled codex/opencode shims. The primary `subagent-model-routing` skill handles
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
- `agents/{codex,opencode}-shim.md` — the Sonnet transport agent contracts.
- `hooks/` — the Stop-hook tripwire (flags a DAG run that leaked to direct dispatch). Disable via the plugin or `hooks/hooks.json`.

## Shims (bundled)

The shims are bundled under `scripts/` and installed onto `~/.claude/scripts/{codex,opencode}-shim.sh` by `scripts/install.sh`. They are not external prerequisites.

```bash
test -x ~/.claude/scripts/codex-shim.sh && test -x ~/.claude/scripts/opencode-shim.sh && echo "shims present"
```

Active routes are GPT via `codex-shim` and Kimi/GLM/MiniMax/local models via `opencode-shim`. The bundled shims log quantitative ledger records with `"source":"shim"` (`event`: `started`/`finished`) and emit a final `SHIM-DONE exit=<n>` sentinel per run.

**Tier example (seed — maintain via `/subagent-model-routing-claude:distill` and your own ledger):**
codex GPT-5.5 ≥ GLM-5.2 (Opus peer, default author) > Kimi K2.7 > MiniMax-M3 (Sonnet peer); local/self-hosted models unranked pending benchmark.

## Prompt references

The runtime skill includes compact prompt cards for codex/GPT, Kimi, GLM, MiniMax, and Qwen. The full references live in the repo-level `prompting/` directory; start with `prompting/00-prompt-reference-index.md` when updating model-specific guidance. Local/self-hosted models (including Qwen) route through the `opencode-shim` custom-provider path; see the root README for an example.
