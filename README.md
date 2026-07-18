# subagent-model-routing

You probably pay for more than one AI coding subscription. Delegating a task between Claude Code, Codex, Grok, Kimi, GLM, MiniMax, or a local model still means copy-pasting the prompt, watching another CLI, and pasting the answer back. That friction makes cross-model review easy to skip.

**subagent-model-routing** makes that handoff explicit with three pieces:

- **Five thin CLI shims** (`codex-shim.sh`, `claude-shim.sh`, `kimi-shim.sh`, `opencode-shim.sh`, and `grok-shim.sh`) backed by a shared local Python runtime. They dispatch a prompt to another agentic CLI and return the answer with a `SHIM-DONE exit=<n>` sentinel, while retaining private run records for inspection and recovery.
- **A routing skill** that defines when to delegate, which model to use, and how to phrase the dispatch, plus **tripwire guardrails** that catch silent delegation failures (missing sentinel, nonzero exit, truncated output) before they enter your context as usable results.
- **A model ledger** that records every dispatch's wall time, exit code, and outcome, so routing decisions improve from your own observations rather than someone else's defaults.

It's built for **Claude Code, Codex, and GitHub Copilot CLI users** who want to route work through the other installed agentic CLIs. Each host stays native for its own model family: Claude Code uses native Claude agents, Codex keeps Codex work inline, and shims handle cross-harness delegation.

The shared installer provides `~/.claude/scripts/model-routing` plus `codex-shim.sh` (GPT models via Codex), `claude-shim.sh` (Claude models via Claude Code), `kimi-shim.sh` (Kimi models via Kimi Code), `grok-shim.sh` (Grok 4.5 via Grok Build), and `opencode-shim.sh` (GLM, MiniMax, Qwen, local models, and any OpenCode provider). The Claude Code package targets codex, kimi, grok, and opencode; the Codex package targets claude, kimi, grok, and opencode; Copilot can target all five. Routed models can edit files and run commands in your workspace, then report completion with a `SHIM-DONE exit=<n>` sentinel.

## How this compares

**Isn't this just an LLM router?** No. Routers like LiteLLM or OpenRouter multiplex API requests to a single endpoint — you send a completion request, they pick a backend and proxy it. subagent-model-routing operates a layer above that: it delegates whole units of agentic work to full CLI harnesses, each with its own tools, workspace access, and subscription auth, then verifies the work actually finished. Nothing here proxies API calls.

**Why not just use OpenCode directly?** You can — and this project composes with OpenCode rather than replacing it. OpenCode remains the generic harness for GLM, MiniMax, Qwen, and local/custom providers, while Kimi can use its dedicated Kimi Code harness. What subagent-model-routing adds on top is the delegation doctrine, completion verification through the sentinel contract, guardrails against silent delegation failure, and a ledger that learns which model to trust for what from your own outcomes.

**Why not do everything in Claude Code?** If one subscription covers all your usage, you don't need this. It exists for people who hold several model subscriptions and want their orchestrator to spend each one where it is strongest — without copy-pasting prompts between terminals by hand.

## Prerequisites

- **Python 3.11 or newer** for the shared runtime. The installer rejects older interpreters with a concrete error.
- **GNU `timeout` or `gtimeout`** remains a compatibility prerequisite. The Python runtime supervises the child process group itself, but the public shims preserve the established missing-timeout exit and ledger behavior.
- **Provider CLIs**: install any transport harnesses you plan to use—[Codex](https://github.com/openai/codex), [Claude Code](https://code.claude.com/docs/en/getting-started), [Grok Build](https://docs.x.ai/build/overview), [Kimi Code](https://moonshotai.github.io/kimi-code/), and/or [OpenCode](https://opencode.ai). Interactive bootstrap offers a checkbox installer for missing CLIs; manual provider installation remains supported.
- **Provider authentication** remains a separate post-install step: `codex login`, `claude auth login`, `grok login` (or `XAI_API_KEY`), `kimi login`, and `opencode auth login`. OpenCode also needs at least one configured provider (`opencode models`).
- GitHub Copilot CLI users also need that CLI installed; the transport shims invoke Codex, Claude Code, Kimi Code, Grok Build, or OpenCode independently of the host client.

## Install

Before piping the installer to your shell, review `scripts/bootstrap.sh`. By default, the shims bypass the dispatched CLI's sandbox and approval prompts (`SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1`) because unattended dispatch cannot answer prompts. Set `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0` to use the CLI's own policy. The [Security note](#security-note) covers the tradeoff.

1. Run the clone-optional bootstrap installer:

```bash
curl -fsSL https://raw.githubusercontent.com/Buckeyes22/subagent-model-routing/v0.6.0/scripts/bootstrap.sh | bash
curl -fsSL https://raw.githubusercontent.com/Buckeyes22/subagent-model-routing/v0.6.0/scripts/bootstrap.sh | bash -s -- --register
```

The recommended command pins both the fetched bootstrap script and cloned checkout to release `v0.6.0`. It clones to `~/.local/share/subagent-model-routing` (override with `SUBAGENT_MODEL_ROUTING_HOME`), installs the shims to `~/.claude/scripts/`, offers an optional checkbox screen for missing provider CLIs, and prints (or runs, with `--register`) each detected client's plugin-install commands. Missing providers start unchecked, installed providers cannot be selected, and a second confirmation shows the first-party source domains and checksum status before download.

To deliberately track the mutable development branch instead, fetch the `main` script and request that ref explicitly:

```bash
curl -fsSL https://raw.githubusercontent.com/Buckeyes22/subagent-model-routing/main/scripts/bootstrap.sh | bash -s -- --ref main
```

The selector reads `/dev/tty`, so it works when bootstrap itself arrives through `curl | bash`. Noninteractive runs never block or install providers; use `--no-provider-menu` to skip explicitly, `--provider-menu` to require the screen, or rerun it later:

```bash
~/.claude/scripts/model-routing setup providers
~/.claude/scripts/model-routing setup providers --dry-run
```

Provider installation never performs authentication or model/provider configuration. See [optional provider CLI setup](docs/provider-cli-setup.md) for sources, platform support, failure recovery, and security controls.

### Manual install (clone anywhere)

```bash
cd <repo>
scripts/install.sh
~/.claude/scripts/model-routing setup providers
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
printf 'Reply with exactly: pong\n' | ~/.claude/scripts/kimi-shim.sh -
printf 'Reply with exactly: pong\n' | ~/.claude/scripts/grok-shim.sh - --effort low
printf 'Reply with exactly: pong\n' | ~/.claude/scripts/claude-shim.sh - --model haiku
```

Expected output:

```
pong
SHIM-DONE exit=0
```

The body before the sentinel varies by child CLI. The `SHIM-DONE exit=<n>` line is the stable tripwire: if it is missing or reports a nonzero exit, the dispatch failed and the skill will not treat the output as successful.

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
kimi-shim.sh prompt.md --model kimi-code/kimi-for-coding
grok-shim.sh prompt.md --effort medium
claude-shim.sh prompt.md --model opus
```

Each shim prints the model's answer followed by `SHIM-DONE exit=<n>`. Use `codex-shim.sh` for GPT models, `claude-shim.sh` for Claude models, `kimi-shim.sh` for Kimi Code, and `grok-shim.sh` for Grok 4.5.

Direct shim calls use the current directory by default. For an implementation that must not touch the caller's worktree, opt into an isolated Git worktree and declare that the task writes:

```bash
codex-shim.sh prompt.md --routing-workspace isolated --routing-task-mode write
model-routing runs diff <dispatch-id>
model-routing runs apply <dispatch-id> --target <repo>
model-routing runs discard <dispatch-id> --yes
```

Nothing is applied or discarded automatically.

### 5. Durable dependency workflow (Codex / Copilot)

For a dependency graph that needs bounded concurrency, context handoff, retries, verification, cancellation, or resume, use the host-neutral runner:

```bash
model-routing workflow run workflow.json --host copilot
model-routing workflow list
model-routing workflow show <workflow-id>
model-routing workflow cancel <workflow-id>
model-routing workflow resume <workflow-id> --host copilot
```

Codex-hosted workflows may contain Claude, Kimi, Grok, and OpenCode transport tasks because Codex work stays inline. Copilot permits all five providers. Claude Code continues to prefer native Workflow; its external-only runner usage does not replace the tripwire hooks. See [host-neutral workflows](docs/workflows.md).

## Day-to-day use

In normal use you don't run the shims by hand — you ask in plain language: "route this to Claude", "get Grok's second opinion", or "fan this review out across Codex and GLM and compare". The routing skill decides the shape of the work: independent one-shot dispatches run flat, Claude-hosted dependency graphs use native Workflow by default, and Codex/Copilot can execute durable JSON graphs through `model-routing workflow`.

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

Run the bootstrap command for the release you want. It verifies the existing clone's origin, fetches the requested tag or branch, and checks out that exact fetched commit before running the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/Buckeyes22/subagent-model-routing/v0.6.0/scripts/bootstrap.sh | bash
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
rm ~/.claude/scripts/model-routing ~/.claude/scripts/codex-shim.sh ~/.claude/scripts/claude-shim.sh ~/.claude/scripts/kimi-shim.sh ~/.claude/scripts/opencode-shim.sh ~/.claude/scripts/grok-shim.sh
rm -rf ~/.local/share/subagent-model-routing
```

## Troubleshooting

- Smoke test returns nothing or no pong → the provider is not authenticated or named wrong; run `kimi login`, `opencode models`, `codex login`, `claude auth status`, or `grok login` for the selected route and retry.
- Provider setup partially failed → rerun `model-routing setup providers`; successful installs are detected and disabled, so only missing CLIs remain selectable. Use `--dry-run` to review sources without downloading.
- Provider setup was skipped in CI or a pipe → this is expected without `/dev/tty`; run `model-routing setup providers` later from a terminal.
- Output ends without `SHIM-DONE exit=<n>` → the run was clipped or timed out; split the task or raise `SHIM_TIMEOUT_SECS` deliberately.
- The skill doesn't trigger → mention subagent-model-routing or a model by name in your ask, or use `/subagent-model-routing-claude:dag-routing` directly.
- A `LEDGER:` or `TRIPWIRE:` message appeared → that's the guardrail layer working; see [Day-to-day use](#day-to-day-use).

## Configuration

### Shim environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SHIM_TIMEOUT_SECS` | `1140` (~19 min) | per-dispatch wall ceiling enforced by process-group supervision; raise deliberately for long jobs |
| `SUBAGENT_MODEL_ROUTING_UNRESTRICTED` | `1` | `1` = bypass the child CLI's sandbox/approval prompts (unattended dispatch); `0` = keep the CLI's own policy |
| `SUBAGENT_MODEL_ROUTING_LEDGER` | `~/.claude/subagent-model-routing/ledger/observations.jsonl` | where quantitative dispatch records append |
| `SUBAGENT_MODEL_ROUTING_HOME` | `~/.local/share/subagent-model-routing` | writable source checkout used by the Claude `distill` command when it is not run inside the checkout |
| `SUBAGENT_MODEL_ROUTING_STATE_HOME` | `${XDG_STATE_HOME:-~/.local/state}/subagent-model-routing` | optional override for private run records and the global lifecycle event stream |
| `CODEX_BIN` | `codex` on `PATH` | explicit Codex executable override (new in v0.3; leaving it unset preserves existing lookup) |
| `OPENCODE_BIN` | auto-detected | explicit path to the opencode binary |
| `GROK_BIN` | auto-detected | explicit path to the Grok Build `grok` binary |
| `KIMI_BIN` | auto-detected | explicit path to the Kimi Code `kimi` binary |
| `KIMI_MODEL_NAME` | unset | Kimi Code's documented temporary model override; lower priority than a shim `-m`/`--model` argument and higher priority than `config.toml` |
| `KIMI_DISABLE_TELEMETRY` | unset | set to `1` to disable Kimi Code's native anonymous telemetry; shared shim run records remain enabled |
| `CLAUDE_BIN` | auto-detected | explicit path to the Claude Code `claude` binary |
| `OPENCODE_OTLP_ENDPOINT` | unset | setting it enables opencode telemetry and auto-fills companion vars (see [Observability](#observability)) |
| `OTEL_RESOURCE_ATTRIBUTES` | unset | codex-shim appends `gen_ai.request.model=<model>` for span attribution |

### Run records and lifecycle hooks

Each accepted dispatch gets a UUID and a private directory under `${XDG_STATE_HOME:-~/.local/state}/subagent-model-routing/runs/`. Inspect it without parsing shim output:

```bash
~/.claude/scripts/model-routing runs list
~/.claude/scripts/model-routing runs show <dispatch-id-or-unique-prefix>
~/.claude/scripts/model-routing runs logs <dispatch-id-or-unique-prefix> --channel both
~/.claude/scripts/model-routing runs cleanup --older-than 30
```

Directories use mode `0700` and files use `0600`. `request.json` retains only prompt metadata and a SHA-256 digest by default; pass `--routing-retain-prompt` to a shim only when you explicitly want `prompt.md` retained. Provider stdout and stderr are always logged because they are needed for recovery, and may themselves contain source code or secrets.

Portable lifecycle hooks are configured in `${XDG_CONFIG_HOME:-~/.config}/subagent-model-routing/hooks.json`. Hook commands are argument arrays, receive event JSON on stdin, have independent timeouts, and fail open. Their stdout and stderr are captured below the run directory and never mixed with provider output or printed after the sentinel. See [Lifecycle hooks](docs/lifecycle-hooks.md).

### Doctor and isolated worktrees

The default doctor is local, read-only, and performs no live model discovery:

```bash
~/.claude/scripts/model-routing doctor
~/.claude/scripts/model-routing doctor --json
~/.claude/scripts/model-routing doctor --provider codex
~/.claude/scripts/model-routing doctor --installation-only
~/.claude/scripts/model-routing doctor --provider claude --live-auth
~/.claude/scripts/model-routing doctor --discover-models
~/.claude/scripts/model-routing doctor --provider opencode --discover-models
~/.claude/scripts/model-routing doctor --provider kimi --discover-models
```

`--live-auth` is required before a documented read-only authentication probe can run. Kimi Code exposes no read-only authentication-status command, so its auth check remains `SKIP`; the default Kimi provider check instead runs the documented, non-mutating `kimi doctor config`. `--discover-models` is separately explicit: OpenCode invokes `opencode models`, Kimi invokes `kimi provider list --json` and retains only validated model-alias keys, and Codex reads its CLI-managed local model cache. Changed output or unavailable discovery is a warning, and the default doctor/preflight never discovers models. Unknown IDs remain pass-through wherever the registry permits them.

Workspace flags are additive and removed before provider arguments are forwarded:

- `--routing-workspace shared|isolated|auto`
- `--routing-task-mode read|write` (`auto` refuses to guess when this is absent)
- `--routing-base <commit>` (required when isolating from a dirty source worktree)

Isolated branches and worktrees remain available for review until `runs discard`. `runs cleanup` deliberately skips active worktrees. See [Doctor](docs/doctor.md), [isolated worktree dispatch](docs/worktree-dispatch.md), and [host-neutral workflows](docs/workflows.md).

### Installer overrides

- `SUBAGENT_MODEL_ROUTING_HOME` — clone location (default `~/.local/share/subagent-model-routing`)
- `SUBAGENT_MODEL_ROUTING_REPO_URL` — git source
- `SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR` — shim install dir (default `~/.claude/scripts`)
- `--register` — run each detected client's plugin-install commands instead of just printing them
- `--provider-menu` — require the optional provider checkbox screen; fail if `/dev/tty` is unavailable
- `--no-provider-menu` — skip optional provider CLI setup

### Choosing models per dispatch

- **opencode-shim** — the first argument IS the model: any `provider/model` from `opencode models`. Extra flags after the prompt file are forwarded to `opencode run` (e.g. `--variant high`, `--thinking`).
- **kimi-shim** — model precedence is explicit `-m`/`--model`, then `KIMI_MODEL_NAME`, then `default_model` from `${KIMI_CODE_HOME:-~/.kimi-code}/config.toml`. It invokes Kimi's non-interactive `--prompt` mode with text output. That mode applies Kimi's auto permission policy while preserving static deny rules, so the shim rejects the incompatible `-y`/`--yolo`/`--auto` flags and reserves `-p`/`--prompt`/`--output-format` for its own transport contract. Kimi Code exposes no per-invocation effort flag in this CLI surface.
- **codex-shim** — uses your `~/.codex/config.toml` default model; override per dispatch with `-m <model>` (or `--model=<model>`) and reasoning effort with `-c model_reasoning_effort=<effort>`. Current Codex runtime model IDs are `gpt-5.6-sol` for Sol (flagship), `gpt-5.6-terra` for Terra (balanced), and `gpt-5.6-luna` for Luna (fast and affordable). The shim is a generic pass-through and will forward other model IDs accepted by the installed Codex CLI.
- **grok-shim** — defaults to `grok-4.5`; override with `-m <model>` or `--model=<model>`, and select Grok 4.5 reasoning effort with `--effort low|medium|high` (xAI's default is `high`). Extra flags after the prompt source are forwarded to `grok`.
- **claude-shim** — defaults to the latest `sonnet` alias; use Sonnet 5 as the normal workhorse, `--model opus` for difficult or verification-heavy work, and `--model fable` for the hardest generally available Claude work where its safeguards and possible fallback are acceptable. `--model haiku` and full-name overrides remain available, and `--effort` must be compatible with the selected model. The shim runs print mode with text output and no session persistence; extra flags such as `--max-turns` or `--max-budget-usd` are forwarded. This project intentionally defines no Mythos-specific reference or route.

### Where the deeper config lives

- **opencode providers/auth** → the [Routing a local model](#routing-a-local-model) section + the [OpenCode docs](https://opencode.ai/docs/providers)
- **Kimi models/auth** → the [Kimi Code CLI docs](https://moonshotai.github.io/kimi-code/)
- **Model tiers and capability cards** → the [Ledger](#the-ledger-and-subagent-model-routing-claudedistill) section (`/subagent-model-routing-claude:distill`)
- **Guardrail hooks** → `plugins/subagent-model-routing-claude/hooks/hooks.json` (delete `Stop` entries or disable the plugin to turn them off)

## Security note

The shims default to `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1`, which bypasses the child CLI's sandbox or interactive approval prompts where that CLI supports a compatible flag. Set it to `0` to retain the provider's configured policy. Kimi's `--prompt` mode is inherently unattended and applies its auto approval policy while retaining static deny rules; it has no compatible restricted-mode switch, and the Kimi shim rejects `-y`/`--yolo`/`--auto` instead of forwarding conflicting flags. Grok Build's sandbox is off by default, so forward an explicit policy such as `--sandbox workspace` when you need isolation. A Git worktree separates files from the caller's checkout but is not a container or permission boundary. Review model-generated patches before applying them.

The optional provider selector is a separate explicit mutation surface. It downloads only checked, missing providers from fixed first-party HTTPS URLs, validates every redirect hop and the final host, bounds size, verifies a reviewed SHA-256 digest when one is available, shows the source and checksum status, confirms again, executes a private temporary script without shell interpolation, and never logs in. A provider whose endpoint could not be checksum-pinned is labeled with an explicit warning and still fails closed on unexpected redirects. Review the full [provider setup security boundary](docs/provider-cli-setup.md#security-boundary) before using it.

## Observability

The built-in, always-on layers are the compatibility ledger JSONL (`~/.claude/subagent-model-routing/ledger/observations.jsonl`) and the structured run store. `started` records mark the beginning of dispatch and `finished` records carry `wall_s`, `exit`, and `outcome`; additive fields include the dispatch UUID and whether the Python supervisor actually fired its timeout.

For OpenCode spans, export `OPENCODE_OTLP_ENDPOINT` before dispatch and the shim fills the companion telemetry variables:

```bash
export OPENCODE_OTLP_ENDPOINT=http://localhost:4318
```

Spans flow to any OTLP-compatible collector or an observability platform like Langfuse.

For Codex spans, Codex honors standard `OTEL_*` environment configuration, and the shim appends `gen_ai.request.model` to `OTEL_RESOURCE_ATTRIBUTES` so each dispatch carries model attribution.

Kimi Code does not expose an OTLP export surface in its documented CLI configuration. Set `KIMI_DISABLE_TELEMETRY=1` to disable its native anonymous telemetry; the shim's local ledger and private run records still provide dispatch attribution and outcomes.

Nothing is emitted unless you configure a collector.

## The ledger and `/subagent-model-routing-claude:distill`

The shim logs `event: started` when dispatch begins and `event: finished` when it ends; finished records carry `wall_s`, `exit`, and `outcome`. Rankings, model cards, and capability claims in this repo are seed examples only. Run `/subagent-model-routing-claude:distill` to promote your own observations into the warm-tier skill cards and rankings, then evolve them from your own records instead of treating defaults as authority.

## Documentation

- **Per-client guides** — [Claude Code package](plugins/subagent-model-routing-claude/README.md), [Codex package](plugins/subagent-model-routing-codex/README.md), [GitHub Copilot CLI package](plugins/subagent-model-routing-copilot/README.md): install details, what each package contains, and client-specific usage.
- **[The routing skill](plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md)** — the full doctrine: the flat-vs-DAG decision, model picking, dispatch patterns, failure modes, and the anti-leak gates. This is what Claude loads at runtime.
- **[Architecture internals](plugins/subagent-model-routing-claude/skills/subagent-model-routing/ARCHITECTURE.md)** — how a Workflow DAG node actually reaches an external model, layer by layer.
- **[Runtime architecture](docs/architecture.md)**, **[provider registry](docs/provider-registry.md)**, **[provider CLI setup](docs/provider-cli-setup.md)**, **[run records](docs/run-records.md)**, **[lifecycle hooks](docs/lifecycle-hooks.md)**, **[doctor](docs/doctor.md)**, **[isolated worktree dispatch](docs/worktree-dispatch.md)**, **[host-neutral workflows](docs/workflows.md)**, and **[public releases](docs/releasing.md)** — the execution, diagnostics, installation, state, generation, integration, and publication contracts.
- **[v0.3 runtime migration](docs/migration-v0.3.md)**, **[v0.4 diagnostics/worktree migration](docs/migration-v0.4.md)**, and **[v0.5 discovery/workflow migration](docs/migration-v0.5.md)** — additive upgrade behavior and compatibility boundaries.
- **[Prompting references](prompting/00-prompt-reference-index.md)** — model and transport guides for [Codex/GPT](prompting/openai-codex-gpt-prompting-reference.md), [Claude Code transport](prompting/anthropic-claude-code-prompting-reference.md), [Claude Sonnet 5](prompting/anthropic-claude-sonnet-5-prompting-reference.md), [Claude Opus 4.8](prompting/anthropic-claude-opus-4.8-prompting-reference.md), [Claude Fable 5](prompting/anthropic-claude-fable-5-prompting-reference.md), [Grok](prompting/xai-grok-prompting-reference.md), [Kimi](prompting/kimi-moonshot-prompting-reference.md), [GLM](prompting/glm-zhipu-prompting-reference.md), [MiniMax](prompting/minimax-prompting-reference.md), and [Qwen](prompting/qwen-alibaba-prompting-reference.md).
- **[Worked example](examples/fan-out-review/README.md)** — a real two-model fan-out review of a planted-bug module, with the actual (lightly trimmed) shim outputs.
- **[Capability cards](plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger/)** — the seed per-model cards the ledger system maintains.
- **[Contributing](CONTRIBUTING.md)** — local checks and conventions for PRs.

## Packages and repo layout

| Client | Marketplace | Package | Dispatch style |
|--------|-------------|---------|----------------|
| Claude Code | `subagent-model-routing` | [`plugins/subagent-model-routing-claude`](plugins/subagent-model-routing-claude/README.md) | native Claude + Codex/Kimi/OpenCode/Grok targets; flat dispatch + Workflow DAG orchestration |
| Codex | `subagent-model-routing-local` | [`plugins/subagent-model-routing-codex`](plugins/subagent-model-routing-codex/README.md) | native Codex + direct or dependency-workflow Claude/Kimi/OpenCode/Grok targets |
| GitHub Copilot CLI | `subagent-model-routing-local` | [`plugins/subagent-model-routing-copilot`](plugins/subagent-model-routing-copilot/README.md) | direct or dependency-workflow dispatch through all five shims |

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

This is an early-stage project at v0.6.0, built and maintained by a single maintainer. Issues and pull requests are welcome, with best-effort response times. The public contract — the `SHIM-DONE` sentinel, the shim environment-variable names, the namespaced agent types, and the versioned workflow schema — is stable and versioned per [CHANGELOG.md](CHANGELOG.md). Expect the rough edges of a young project, and please report them.

## License

MIT © Buckeyes22
