---
name: subagent-model-routing
description: >-
  Copilot-compatible workflow for routing work to local external-model shims:
  codex/GPT-5.x through codex-shim.sh and Kimi/GLM/MiniMax through
  opencode-shim.sh. Local/self-hosted models (including Qwen) route through
  opencode-shim.sh as a custom provider. Use when the user asks Copilot to
  dispatch, compare, review, fan out, or sequence work across those local shims.
  This port intentionally avoids Claude Code orchestration DAGs,
  transport-agent, command, and hook surfaces.
---

# Model Routing For Copilot

This is the Copilot-compatible companion to the Claude Code `subagent-model-routing-claude` plugin. It uses the same local shim scripts, but not the Claude Code transport layer.

Use it when the user wants Copilot to route work to external model harnesses through:

- `~/.claude/scripts/codex-shim.sh` for GPT-5.x via the local codex CLI wrapper.
- `~/.claude/scripts/opencode-shim.sh` for Kimi, GLM, MiniMax, or local/self-hosted models via the local opencode wrapper.

Local/self-hosted models (including Qwen) are routed as custom providers through `opencode-shim.sh`; see the root README for an example.

Do not use Claude-only concepts here. In Copilot, there is no Claude-only DAG runtime, no Claude transport-agent prose, and no Claude command wrapper. The Copilot path is direct shell orchestration through prompt files and shim commands.

## First Decision

Before dispatching, classify the task.

### Flat dispatch

Flat dispatch means independent one-shot work with no dependency edge between units. Examples:

- Ask Kimi and codex for independent reviews, then compare findings yourself.
- Send N unrelated files/prompts for classification.
- Generate two candidate implementations from the same prompt, then synthesize inline.

For flat work, write prompt files under `/tmp/subagent-model-routing-<task>/` and run the relevant shim commands directly from the shell. Same-turn collation by Copilot does not make a workflow.

### Dependency workflow

Dependency workflow means there are edges: A must finish before B can start, an upstream artifact is read by a downstream prompt, a mechanical reduce needs all prior outputs, or Copilot must judge/synthesize between stages.

For dependency work in Copilot:

1. Keep the graph in the main Copilot thread.
2. Write every prompt file up front where possible.
3. Run upstream shim commands first.
4. Verify each produced file with filesystem checks.
5. Read or synthesize the upstream result inline.
6. Only then run downstream shim commands.

If the user explicitly asks for parallel model work, use independent shim calls for independent read-heavy exploration or parallel checks. Do not hide dependency edges inside a single undifferentiated shell batch.

## Preflight

Run these before first use on a machine or when auth is suspect:

```bash
test -x ~/.claude/scripts/codex-shim.sh
test -x ~/.claude/scripts/opencode-shim.sh
mkdir -p /tmp/subagent-model-routing-pilot
printf 'Reply with exactly: pong\n' > /tmp/subagent-model-routing-pilot/pong.md
~/.claude/scripts/opencode-shim.sh kimi-for-coding/k2p7 /tmp/subagent-model-routing-pilot/pong.md 2>/dev/null | grep -m1 -i pong
~/.claude/scripts/codex-shim.sh /tmp/subagent-model-routing-pilot/pong.md -c model_reasoning_effort=low | grep -m1 -i pong
```

If a pong fails, fix shim provider config, endpoint reachability, or local installation before using this skill for real work.

## Prompt File Pattern

Use files as the boundary between Copilot and the external harness.

```bash
DIR=/tmp/subagent-model-routing-task
mkdir -p "$DIR"
cat > "$DIR/review.md" <<'EOF'
Review the repository for correctness bugs.
Write findings with file paths, line references, severity, and evidence.
Do not make code changes.
EOF
~/.claude/scripts/opencode-shim.sh kimi-for-coding/k2p7 "$DIR/review.md"
# Local/self-hosted models route through opencode-shim as a custom provider.
```

For authoring tasks, tell the external harness exactly which files it may edit and which verification command it must run. After the shim returns, Copilot must inspect the diff and run verification itself.

## Model Routes

- Codex/GPT route: `~/.claude/scripts/codex-shim.sh <prompt-file> [flags]`
- Kimi route: `~/.claude/scripts/opencode-shim.sh kimi-for-coding/k2p7 <prompt-file>`
- GLM route: `~/.claude/scripts/opencode-shim.sh zai-coding-plan/glm-5.2 <prompt-file>`
- MiniMax route: `~/.claude/scripts/opencode-shim.sh minimax/MiniMax-M3 <prompt-file>` (append `--thinking` only when you want the reasoning trace surfaced)
- Local/self-hosted route (including Qwen): `~/.claude/scripts/opencode-shim.sh <custom-provider/model> <prompt-file> [flags]` — see the root README for an example.

**Tier example (seed — copy into your own ledger and adjust):**
codex GPT-5.5 ≥ GLM-5.2 > Kimi K2.7 > MiniMax-M3; local/self-hosted models unranked pending benchmark. GLM-5.2 holds the default authoring seat; codex is reserved for the hardest/critical units and deepest review; Kimi is mid-tier utility, parallel candidates, and burst; MiniMax M3 handles Sonnet-grade throughput (stall policy retained). Use GLM-5.2 for default authoring and review, codex for the hardest/critical units and deepest review, Kimi for mid-tier authoring and parallel candidates, MiniMax for Sonnet-grade throughput, and local/self-hosted models for provider-specific experiments or air-gapped work.

Per-model capability cards (excels-at / struggles-with / operational caveats / evidence) live in the Claude Code package within this repo clone at `plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger/{codex,glm,kimi,minimax,qwen}.md`. They are maintained there by that package's `/subagent-model-routing-claude:distill` command and are read-only reference material from Codex/Copilot; they are present in the repo clone but not in an isolated plugin-cache install.

Per-dispatch ceiling: the bundled shim enforces `SHIM_TIMEOUT_SECS` (default 1140s, about 19 min) per run and emits a final `SHIM-DONE exit=<n>` sentinel; its absence in a captured blob signals clipped or still-running output. Long flat jobs (>~15 min expected wall): split the prompt into smaller units, or raise `SHIM_TIMEOUT_SECS` (and your host agent's own command timeout) deliberately.

## Prompt Reference Cards

Use these cards when writing prompt files for the local shims. They are compact runtime summaries; the canonical references live under `prompting/` and are indexed in `prompting/00-prompt-reference-index.md`. For new, high-stakes, broad fan-out, or reusable prompt templates, open the full reference before dispatch.

### codex / GPT

- Use Goal, Context, Constraints, and Completion Criteria.
- Name allowed files, allowed edits, validation commands, and exact completion criteria.
- Include deterministic verification such as tests, typecheck, lint, or static detectors.
- Add an initiative nudge before raising effort when the model stops at the first plausible answer.
- Tools: if your CLI has MCP tools configured, prompts may direct their use.
- Full reference: `prompting/openai-codex-gpt-prompting-reference.md`

### Kimi / Moonshot

- Use clear detailed instructions, delimiters, explicit steps, examples, and reference text.
- Keep shim prompts focused on task and output contract; opencode owns the tool harness.
- Pilot new templates before fan-out.
- Do not use non-tool completion routes for grounded review.
- Tools: if your CLI has MCP tools configured, prompts may direct their use.
- Full reference: `prompting/kimi-moonshot-prompting-reference.md`

### GLM / Z.ai

- Put critical instructions early when useful, but treat that as a field heuristic to validate, not a vendor guarantee.
- Use a concrete role, delimiters, exact JSON/output formats, and decomposed subtasks.
- Prefer explicit thinking controls when available.
- Through the shim, demand parseable JSON when JSON is required and validate after return.
- Tools: if your CLI has MCP tools configured, prompts may direct their use.
- Full reference: `prompting/glm-zhipu-prompting-reference.md`

### MiniMax

- MiniMax has no official text prompt-engineering guide; use Anthropic-style structured prompts.
- Give clear role, task, success criteria, constraints, and output shape.
- Allow architect-style planning for coding prompts when useful.
- Treat `--thinking` as a binary visibility toggle, not an effort dial.
- Detect missing text stalls and retry the same model up to 3 times.
- Tools: if your CLI has MCP tools configured, prompts may direct their use.
- Full reference: `prompting/minimax-prompting-reference.md`

### Qwen / Alibaba

- Route status: any OpenAI-compatible endpoint (local or hosted) via an opencode custom provider — route through `~/.claude/scripts/opencode-shim.sh` with your custom-provider entry; see the root README for an example.
- Use the six-element framework for prompt work: Context, Objective, Style, Tone, Audience, Response.
- Add examples, explicit task steps, and separators such as `###`, `===`, or `>>>`.
- Qwen3 thinking can be steered with `enable_thinking`, `/think`, and `/no_think`.
- Do not route local Qwen work through `codex-shim`; use the `opencode-shim` custom-provider route.
- Tools: MCP tool availability follows your opencode configuration; for small-context local models, consider skipping heavy tool schemas — context is better spent on prompt and source.
- Full reference: `prompting/qwen-alibaba-prompting-reference.md`
