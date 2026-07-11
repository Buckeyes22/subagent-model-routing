# subagent-model-routing

You probably pay for more than one AI coding subscription. Claude Code is a strong orchestrator, but delegating a task to Codex, Kimi, GLM, MiniMax, or a local model still means copy-pasting the prompt, watching another CLI, and pasting the answer back. That friction makes cross-model review easy to skip.

**subagent-model-routing** makes that handoff explicit with three pieces:

- **Two thin CLI shims** (`codex-shim.sh` and `opencode-shim.sh`) that dispatch a prompt to any external model and return the answer with a `SHIM-DONE exit=<n>` sentinel, so the orchestrator knows the delegated work finished.
- **A routing skill** that defines when to delegate, which model to use, and how to phrase the dispatch, plus **tripwire guardrails** that catch silent delegation failures (missing sentinel, nonzero exit, truncated output) before they enter your context as usable results.
- **A model ledger** that records every dispatch's wall time, exit code, and outcome, so routing decisions improve from your own observations rather than someone else's defaults.

It's built for **Claude Code users** who also run Codex or OpenCode (or a local model served through OpenCode). Codex and GitHub Copilot CLI users get the same shims for direct-shell dispatch.

Claude Code, Codex, and GitHub Copilot CLI can all route agent work to external models through the same two shims: `~/.claude/scripts/codex-shim.sh` (for GPT models via Codex) and `~/.claude/scripts/opencode-shim.sh` (for Kimi, GLM, MiniMax, and any OpenCode provider). The Claude Code package also includes the routing skill for flat dispatch plus Workflow DAG orchestration; the Codex and GitHub Copilot CLI packages provide direct-shell dispatch. Routed models can edit files and run commands in your workspace, then report completion with a `SHIM-DONE exit=<n>` sentinel.

## How this compares

**Isn't this just an LLM router?** No. Routers like LiteLLM or OpenRouter multiplex API requests to a single endpoint — you send a completion request, they pick a backend and proxy it. subagent-model-routing operates a layer above that: it delegates whole units of agentic work to full CLI harnesses, each with its own tools, workspace access, and subscription auth, then verifies the work actually finished. Nothing here proxies API calls.

**Why not just use OpenCode directly?** You can — and this project composes with OpenCode rather than replacing it. OpenCode is the harness that actually runs Kimi, GLM, MiniMax, or your local models. What subagent-model-routing adds on top is the delegation doctrine (when to route, and to which model), completion verification through the sentinel contract, guardrails against silent delegation failure, and a ledger that learns which model to trust for what from your own outcomes.

**Why not do everything in Claude Code?** If one subscription covers all your usage, you don't need this. It exists for people who hold several model subscriptions and want their orchestrator to spend each one where it is strongest — without copy-pasting prompts between terminals by hand.

## Prerequisites

- **Codex**: install and authenticate the [Codex CLI](https://github.com/openai/codex), then run `codex login`.
- **OpenCode**: install the [OpenCode CLI](https://opencode.ai), run `opencode auth login`, and verify at least one provider with `opencode models`.
- GitHub Copilot CLI users also need that CLI installed, but the shims are Codex/OpenCode only.

## Install

Before piping the installer to your shell, skim `scripts/bootstrap.sh` first; it is ~90 lines. By default, the shims bypass the dispatched CLI's sandbox and approval prompts (`SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1`) because unattended dispatch cannot answer interactive prompts. Set `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0` to use the CLI's own policy. The [Security note](#security-note) covers the tradeoff.

1. Run the clone-optional bootstrap installer:

```bash
curl -fsSL https://raw.githubusercontent.com/Buckeyes22/subagent-model-routing/main/scripts/bootstrap.sh | bash
curl -fsSL https://raw.githubusercontent.com/Buckeyes22/subagent-model-routing/main/scripts/bootstrap.sh | bash -s -- --register
```

It clones to `~/.local/share/subagent-model-routing` (override with `SUBAGENT_MODEL_ROUTING_HOME`), installs the shims to `~/.claude/scripts/`, and prints (or runs, with `--register`) each detected client's plugin-install commands.

### Manual install (clone anywhere)

```bash
cd <repo>
scripts/install.sh
```

Add the local marketplace and install the package for your client.

### Claude Code

```bash
claude plugin marketplace add <repo> --scope user
claude plugin install subagent-model-routing-claude@subagent-model-routing --scope user
```

Useful management and validation commands:

```bash
claude plugin marketplace list
claude plugin marketplace update subagent-model-routing
claude plugin list
claude plugin details subagent-model-routing-claude@subagent-model-routing
claude plugin validate <repo>
claude plugin validate <repo>/plugins/subagent-model-routing-claude
```

The install enables the plugin automatically; if `claude plugin list` ever shows it disabled, re-enable with `claude plugin enable subagent-model-routing-claude@subagent-model-routing --scope user`.

Manual settings equivalent if the CLI marketplace flow is unavailable:

```json
{
  "extraKnownMarketplaces": {
    "subagent-model-routing": {
      "source": { "source": "directory", "path": "<repo>" }
    }
  },
  "enabledPlugins": { "subagent-model-routing-claude@subagent-model-routing": true }
}
```

Then restart Claude Code (or `/hooks`) to load hook changes.

### Codex

```bash
codex plugin marketplace add <repo>
codex plugin add subagent-model-routing-codex@subagent-model-routing-local
```

Useful management and validation commands:

```bash
codex plugin marketplace list
codex plugin list
python3 -m json.tool <repo>/.agents/plugins/marketplace.json >/dev/null
python3 -m json.tool <repo>/plugins/subagent-model-routing-codex/.codex-plugin/plugin.json >/dev/null
```

After changing the Codex package, reinstall it and start a new Codex thread so the updated skill is loaded from the plugin cache.

### GitHub Copilot CLI

```bash
copilot plugin marketplace add <repo>
copilot plugin install subagent-model-routing-copilot@subagent-model-routing-local
```

Useful management commands:

```bash
copilot plugin marketplace list
copilot plugin marketplace browse subagent-model-routing-local
copilot plugin marketplace update subagent-model-routing-local
copilot plugin list
copilot plugin update subagent-model-routing-copilot@subagent-model-routing-local
copilot plugin uninstall subagent-model-routing-copilot
```

## Quickstart

### 1. Transport smoke test

Confirm a shim can reach a model and return the sentinel (substitute any configured provider/model):

```bash
printf 'Reply with exactly: pong\n' | ~/.claude/scripts/opencode-shim.sh <provider/model> -
```

Expected output:

```
> <agent> · <model>
pong
SHIM-DONE exit=0
```

The `SHIM-DONE exit=<n>` line is the tripwire: if it is missing or reports a nonzero exit, the dispatch failed and the skill will not treat the output as successful.

For machine-readable transport metadata, opt in with `SHIM_RESULT=1`:

```bash
printf 'Reply with exactly: pong\n' | SHIM_RESULT=1 ~/.claude/scripts/opencode-shim.sh <provider/model> -
```

A completed child run then ends with this pair:

```text
SHIM-RESULT {"ts":"...","dispatch_id":"opencode-...","shim":"opencode","model":"...","event":"finished","exit":0,"wall_s":2,"outcome":"ok","profile":"unrestricted","source":"shim"}
SHIM-DONE exit=0
```

Only a `SHIM-RESULT` line immediately before the final `SHIM-DONE` is authoritative; a child process can print lookalike lines earlier in its output. Parse the pair safely with the bundled reference parser:

```bash
SHIM_RESULT=1 opencode-shim.sh <provider/model> prompt.md | tee /tmp/shim.out
python3 "${SUBAGENT_MODEL_ROUTING_HOME:-$HOME/.local/share/subagent-model-routing}/scripts/parse-shim-result.py" </tmp/shim.out
```

The receipt is the exact finished JSONL ledger record for that `dispatch_id`. It proves transport completion and reports the active CLI policy profile; it does **not** prove that requested files are correct or that project checks passed. Pre-dispatch failures continue to emit only `SHIM-DONE`.

### 2. First routed dispatch from Claude Code

With the Claude Code plugin installed, ask in natural language:

> Use subagent-model-routing to send a review of src/parser.ts to kimi, get a second opinion from codex, and compare the findings.

The routing skill triggers automatically on routing or delegation requests; you do not invoke it by hand.

### 3. Workflow DAG orchestration

For multi-step delegated work that should run as a dependency graph:

```
/subagent-model-routing-claude:dag-routing review src/parser.ts across kimi and codex, then summarize
```

### 4. Direct-shell usage (Codex / Copilot CLI)

Write a prompt to a file and dispatch it:

```bash
opencode-shim.sh <provider/model> prompt.md
```

The shim prints the model's answer followed by `SHIM-DONE exit=<n>`. Codex users use `codex-shim.sh` the same way for GPT models.

## Day-to-day use

In normal Claude Code work you don't run the shims by hand — you just ask in plain language: "route this to kimi", "get codex's second opinion", "fan this review out across glm and kimi and compare". The routing skill decides the shape of the work: independent one-shot dispatches run flat, while a request that's really a dependency graph runs through the Workflow DAG path. You don't have to pick which — the skill does.

Set expectations on time. A routed dispatch is a full agentic run: the external model reads files, edits, and runs checks in your workspace, then reports back. Substantive dispatches typically take several minutes, not seconds. The shim enforces a per-run ceiling of `SHIM_TIMEOUT_SECS` (default 1140s, ~19 min), so a single dispatch that runs longer than that will be clipped.

The important part — the two Stop-hook nudges. After a turn that dispatched shims, you may see one of two messages appear. Both are normal operation, not errors.

- **Ledger nudge** — a line beginning `subagent-model-routing LEDGER: shims were dispatched this turn and no ledger note was written…`. It's asking whether anything notable happened on that dispatch. Claude answers it — noting anything notable, or stating nothing was — and continues. The ledger improves only if you actually feed it observations.
- **DAG tripwire** — if a DAG-shaped request ran as flat direct dispatches instead, you may see `dag-routing TRIPWIRE: …`, which asks Claude to either redo the work via the Workflow tool or state that flat dispatch was deliberate. Usually it was deliberate, and saying so clears it.

These are advisory, fail-open guardrails. Seeing one is the system working as designed — it never blocks your turn. If you'd rather not see them at all, disable the plugin entirely, or delete the `Stop` entries in `plugins/subagent-model-routing-claude/hooks/hooks.json`.

## Routing a local model

OpenCode supports custom providers. Add a local llama.cpp server (or any OpenAI-compatible endpoint) to `~/.config/opencode/opencode.json` as described in the [OpenCode providers docs](https://opencode.ai/docs/providers):

```jsonc
// ~/.config/opencode/opencode.json
{
  "provider": {
    "local": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Local llama.cpp",
      "options": { "baseURL": "http://localhost:8080/v1" },
      "models": {
        "my-model": { "name": "My local model" }
      }
    }
  }
}
// then: ~/.claude/scripts/opencode-shim.sh local/my-model <prompt-file>
```

The shim will dispatch the prompt file to `local/my-model` and return the result with `SHIM-DONE exit=<n>`.

## Updating and uninstalling

### Update

Re-run the bootstrap one-liner from [Install](#install), or pull the clone directly:

```bash
git -C ~/.local/share/subagent-model-routing pull --ff-only
```

Then refresh the Claude Code marketplace so the plugin picks up the new version:

```bash
claude plugin marketplace update subagent-model-routing
```

### Uninstall

Remove the plugin from each client you installed it into, then drop the shims and the clone:

```bash
claude plugin uninstall subagent-model-routing-claude@subagent-model-routing --scope user
codex plugin remove subagent-model-routing-codex
copilot plugin uninstall subagent-model-routing-copilot
rm ~/.claude/scripts/codex-shim.sh ~/.claude/scripts/opencode-shim.sh
rm -rf ~/.local/share/subagent-model-routing
```

## Troubleshooting

- Smoke test returns nothing or no pong → the provider is not authenticated or named wrong; run `opencode models` (or `codex login`) and retry.
- Output ends without `SHIM-DONE exit=<n>` → the run was clipped or timed out; split the task or raise `SHIM_TIMEOUT_SECS` deliberately.
- The skill doesn't trigger → mention subagent-model-routing or a model by name in your ask, or use `/subagent-model-routing-claude:dag-routing` directly.
- A `LEDGER:` or `TRIPWIRE:` message appeared → that's the guardrail layer working; see [Day-to-day use](#day-to-day-use).

## Configuration

### Shim environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SHIM_TIMEOUT_SECS` | `1140` (~19 min) | per-dispatch wall ceiling enforced with `timeout(1)`; raise deliberately for long jobs |
| `SHIM_RESULT` | `0` | `1` emits the finished ledger record as `SHIM-RESULT <json>` immediately before `SHIM-DONE` |
| `SUBAGENT_MODEL_ROUTING_UNRESTRICTED` | `1` | `1` = bypass the child CLI's sandbox/approval prompts (unattended dispatch); `0` = keep the CLI's own policy |
| `SUBAGENT_MODEL_ROUTING_LEDGER` | `~/.claude/subagent-model-routing/ledger/observations.jsonl` | where quantitative dispatch records append |
| `OPENCODE_BIN` | auto-detected | explicit path to the opencode binary |
| `OPENCODE_OTLP_ENDPOINT` | unset | setting it enables opencode telemetry and auto-fills companion vars (see [Observability](#observability)) |
| `OTEL_RESOURCE_ATTRIBUTES` | unset | codex-shim appends `gen_ai.request.model=<model>` for span attribution |

### Installer overrides

- `SUBAGENT_MODEL_ROUTING_HOME` — clone location (default `~/.local/share/subagent-model-routing`)
- `SUBAGENT_MODEL_ROUTING_REPO_URL` — git source
- `SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR` — shim install dir (default `~/.claude/scripts`)
- `--register` — run each detected client's plugin-install commands instead of just printing them

### Choosing models per dispatch

- **opencode-shim** — the first argument IS the model: any `provider/model` from `opencode models`. Extra flags after the prompt file are forwarded to `opencode run` (e.g. `--variant high`, `--thinking`).
- **codex-shim** — uses your `~/.codex/config.toml` default model; override per dispatch with `-m <model>` and reasoning effort with `-c model_reasoning_effort=low|medium|high`.

### Where the deeper config lives

- **opencode providers/auth** → the [Routing a local model](#routing-a-local-model) section + the [OpenCode docs](https://opencode.ai/docs/providers)
- **Model tiers and capability cards** → the [Ledger](#the-ledger-and-subagent-model-routing-claudedistill) section (`/subagent-model-routing-claude:distill`)
- **Guardrail hooks** → `plugins/subagent-model-routing-claude/hooks/hooks.json` (delete `Stop` entries or disable the plugin to turn them off)

## Security note

The shims default to `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1`, which bypasses the child CLI's sandbox and interactive approval prompts because dispatched work runs unattended. Set `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0` to leave the child CLI's own sandbox/approval policy in effect (Codex then runs with `--sandbox workspace-write`; OpenCode enforces whatever permission configuration you have set). Dispatched models can edit files and run commands in your workspace, so route only work you would trust a non-Claude agent to perform unsupervised.

## Observability

The built-in, always-on layer is the ledger JSONL (`~/.claude/subagent-model-routing/ledger/observations.jsonl`), where `started` records mark the beginning of dispatch and `finished` records carry `dispatch_id`, `wall_s`, `exit`, `outcome`, and `profile`. Set `SHIM_RESULT=1` when a caller also needs the exact finished record on stdout.

For OpenCode spans, export `OPENCODE_OTLP_ENDPOINT` before dispatch and the shim fills the companion telemetry variables:

```bash
export OPENCODE_OTLP_ENDPOINT=http://localhost:4318
```

Spans flow to any OTLP-compatible collector or an observability platform like Langfuse.

For Codex spans, Codex honors standard `OTEL_*` environment configuration, and the shim appends `gen_ai.request.model` to `OTEL_RESOURCE_ATTRIBUTES` so each dispatch carries model attribution.

Nothing is emitted unless you configure a collector.

## The ledger and `/subagent-model-routing-claude:distill`

The shim logs `event: started` when dispatch begins and `event: finished` when it ends; finished records carry `wall_s`, `exit`, and `outcome`. Rankings, model cards, and capability claims in this repo are seed examples only. Run `/subagent-model-routing-claude:distill` to promote your own observations into the warm-tier skill cards and rankings, then evolve them from your own records instead of treating defaults as authority.

## Documentation

- **Per-client guides** — [Claude Code package](plugins/subagent-model-routing-claude/README.md), [Codex package](plugins/subagent-model-routing-codex/README.md), [GitHub Copilot CLI package](plugins/subagent-model-routing-copilot/README.md): install details, what each package contains, and client-specific usage.
- **[The routing skill](plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md)** — the full doctrine: the flat-vs-DAG decision, model picking, dispatch patterns, failure modes, and the anti-leak gates. This is what Claude loads at runtime.
- **[Architecture internals](plugins/subagent-model-routing-claude/skills/subagent-model-routing/ARCHITECTURE.md)** — how a Workflow DAG node actually reaches an external model, layer by layer.
- **[Prompting references](prompting/00-prompt-reference-index.md)** — per-model prompt-engineering guides for [Codex/GPT](prompting/openai-codex-gpt-prompting-reference.md), [Kimi](prompting/kimi-moonshot-prompting-reference.md), [GLM](prompting/glm-zhipu-prompting-reference.md), [MiniMax](prompting/minimax-prompting-reference.md), and [Qwen](prompting/qwen-alibaba-prompting-reference.md).
- **[Worked example](examples/fan-out-review/README.md)** — a real two-model fan-out review of a planted-bug module, with the actual (lightly trimmed) shim outputs.
- **[Capability cards](plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger/)** — the seed per-model cards the ledger system maintains.
- **[Contributing](CONTRIBUTING.md)** — local checks and conventions for PRs.

## Packages and repo layout

| Client | Marketplace | Package | Dispatch style |
|--------|-------------|---------|----------------|
| Claude Code | `subagent-model-routing` | [`plugins/subagent-model-routing-claude`](plugins/subagent-model-routing-claude/README.md) | one skill, flat dispatch + Workflow DAG orchestration |
| Codex | `subagent-model-routing-local` | [`plugins/subagent-model-routing-codex`](plugins/subagent-model-routing-codex/README.md) | direct shell dispatch via `codex-shim.sh + opencode-shim.sh` |
| GitHub Copilot CLI | `subagent-model-routing-local` | [`plugins/subagent-model-routing-copilot`](plugins/subagent-model-routing-copilot/README.md) | direct shell dispatch via `codex-shim.sh + opencode-shim.sh` |

```text
.claude-plugin/marketplace.json          # Claude marketplace
.agents/plugins/marketplace.json         # Codex marketplace
.github/plugin/marketplace.json         # Copilot marketplace
plugins/subagent-model-routing-claude/           # Claude skill + hooks
plugins/subagent-model-routing-codex/            # Codex plugin package
plugins/subagent-model-routing-copilot/          # Copilot plugin package
scripts/                                # bootstrap.sh + install.sh + shims
prompting/                              # model-specific prompt guidance
```

## Project status

This is an early-stage project at v0.2.0, built and maintained by a single maintainer. Issues and pull requests are welcome, with best-effort response times. The public contract — the `SHIM-DONE` sentinel, the opt-in `SHIM-RESULT` receipt, the shim environment-variable names, and the namespaced agent types — is stable and versioned per [CHANGELOG.md](CHANGELOG.md). Expect the rough edges of a young project, and please report them.

## License

MIT © Buckeyes22
