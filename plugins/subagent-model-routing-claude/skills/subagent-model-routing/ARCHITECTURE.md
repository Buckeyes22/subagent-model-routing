# DAG Model Routing — Architecture & Internals

How a `Workflow` DAG actually delegates each node to a non-Claude model. This is the mechanism layer behind `SKILL.md`; read `SKILL.md` first for how to *use* it. Shared transport substrate (model catalog, response parsing, auth pre-flight, failure modes) lives in `SKILL.md` Part B — this doc stops at the shim boundary and points there.

Epistemic note: the `Workflow`-tool hooks and resume semantics are documented behavior; the script *transform* (§2) is inferred from observed behavior (top-level `await`/`return` work; `meta` must be a literal) and verified empirically via `node --check`; the journaling files (§6) and the routing path (§3) are **observed from the real pilot run** (date anonymized).

## 1. The path of a node (one diagram)

```
Opus (main loop)
  │  Workflow({ scriptPath })                      ── opt-in: invoking this skill / the command authorizes it
  ▼
Workflow runtime  ── background task, returns runId immediately; <notification> on completion
  │                                                  ◄── Plane 1: /workflows live progress (phase/label rows)
  │  executes the JS DAG script:
  │    • extracts `export const meta` (must be a pure literal, first statement)
  │    • injects globals: agent() phase() log() pipeline() parallel() args budget workflow()
  │    • effectively wraps the body in an async fn → top-level await + return are legal
  │  each work node is:  agent("Run verbatim: …/codex-shim.sh <file>", { agentType: 'subagent-model-routing-claude:codex-shim', model: 'sonnet' })
  ▼
Workflow agent  ── ONE per node. agentType resolves in the SAME registry as the Agent tool →
  │               adopts the codex-shim / opencode-shim system prompt (Sonnet transport):
  │               "find the command in the prompt, run it via Bash with timeout:1200000,
  │                return stdout verbatim." NO schema ⇒ raw stdout is the node's return value.
  ▼
Bash tool  →  ~/.claude/scripts/{codex,opencode}-shim.sh  <provider/model?>  <prompt-file>  [flags]
  ▼
Shim layer  ── runs the CLI in plain-text mode (+ permission/sandbox bypass unless
  │                                SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0); enforces SHIM_TIMEOUT_SECS; logs
  │                                `"source":"shim"` ledger records and emits the final
  │                                `SHIM-DONE exit=<n>` sentinel as the LAST stdout line
  ▼
codex / opencode CLI  ── full agent loop: read source · write files · run gates (tsc/lint/test) · iterate
  ▼
EXTERNAL MODEL  (GPT-5.x · Kimi K2.7 · GLM-5.2 · MiniMax-M3 · local/self-hosted via opencode custom provider)  ── external auth/local endpoint, OFF the token meter
  │
   └── stdout (the CLI's plain-text output, `SHIM-DONE exit=<n>` last) ─┐
                                                                     │ returned VERBATIM up the chain
    Opus  ◄── DAG return value  ◄── node return  ◄── Sonnet transport ◄┘

    Inter-node data does NOT travel this wire. It travels the FILESYSTEM:
    the CLI layer writes /tmp/dag-<task>/<artifact>; the next node's CLI reads it. (§5)
```

The single most important structural fact: **there are five nested execution contexts**, and the "work" happens in the bottom one (the external model inside the CLI). A node authored without `agentType` collapses the bottom three layers into "a default Claude subagent does the work itself" — the silent leak the skill exists to prevent.

## 2. How the Workflow tool runs a script

The script is plain JavaScript (NOT TypeScript), executed in a sandbox by the `Workflow` runtime — not by `node` directly. Three behaviors you must design around:

- **`meta` extraction.** `export const meta = { name, description, phases? }` must be the first statement and a **pure literal** (no variables, calls, spreads, or template interpolation). The runtime reads it before execution to populate the permission dialog and the progress groups. A computed `meta` is rejected at launch.
- **The transform.** The body uses top-level `await` (e.g. `const x = await agent(...)`) and a top-level `return <value>` — neither is legal in a raw ES module. The runtime therefore **effectively strips `export` and wraps the body in an `async` function**, so `await`/`return` resolve against that wrapper. Consequence for tooling: `node --check raw.mjs` falsely fails ("'return' outside of function"); to syntax-check, replicate the transform first (`SKILL.md` §Smoke test does exactly this).
- **Injected globals, not imports.** `agent`, `phase`, `log`, `pipeline`, `parallel`, `args`, `budget`, and `workflow` are provided by the runtime — there are no `import`/`require`s, no `node:` modules, no filesystem, no network. `Date.now()`, `Math.random()`, and argless `new Date()` **throw** (they would make resume non-deterministic). Standard pure built-ins (`JSON`, `Math.*` except random, `Array`, `String`, …) work.

`agent(prompt, opts)` returns the subagent's final text (a string) when no `schema` is given. With a `schema` it forces a StructuredOutput tool call and returns a validated object — which is why shim nodes pass **no schema**: the shim's contract is "return stdout verbatim," and a schema would graft a structured-output instruction onto the dumb pipe.

## 3. agentType resolution — how a node becomes a model

`opts.agentType` is "resolved from the same registry as the `Agent` tool." Under the plugin install the registered names are namespaced as `subagent-model-routing-claude:codex-shim` and `subagent-model-routing-claude:opencode-shim` (agent defs live in this plugin's `agents/`, Sonnet, `color:` only, no `background`). When a node sets `agentType: 'subagent-model-routing-claude:codex-shim'`:

1. The workflow agent for that node is instantiated with the **codex-shim system prompt** ("find the command, run via Bash `timeout: 1200000`, return stdout verbatim, never use any tool but Bash").
2. The node's `prompt` ("Run verbatim: ~/.claude/scripts/codex-shim.sh …") IS the command the transport agent looks for.
3. The transport runs it; the shim execs the CLI; the CLI drives the external model; stdout flows back as the node's string return.

**The leak path:** `agentType` is matched by string. A typo (`codex_shim`, `codexshim`) or omission does **not** error — it falls back to the default workflow subagent (in-loop Claude with full tools), which then *does the task itself* and returns a plausible result. Nothing distinguishes that from a routed node except the transcript. This is why the skill's defenses are structural (helpers) + mechanical (the audit) rather than "remember to set agentType." Verified in the pilot run: the routed nodes' transcripts carry `"agentType":"subagent-model-routing-claude:codex-shim"`/`"subagent-model-routing-claude:opencode-shim"` and the actual `*-shim.sh` invocations; a leaked node would carry neither.

Composition caveat: when `agentType` is combined with `schema`, the custom agent's system prompt gets a StructuredOutput instruction appended. Shim nodes never use `schema`, so this never applies here — keep it that way.

## 4. The five layers and where their cost/visibility live

| Layer | What it is | Tokens counted? | Visible where |
|---|---|---|---|
| Opus main loop | You, the orchestrator | yes (main) | this session |
| Workflow runtime | the background DAG task | — (orchestration) | `/workflows`, notification |
| Workflow agent (per node) | the node's executor | yes — but it's a **Sonnet transport** agent, small | `/workflows` row (label/phase) |
| Shim subagent system prompt | rides on the node agent | (same agent) | — |
| codex/opencode CLI + external model | the actual work | **NO** — external subscription/account or local endpoint, off-meter | artifacts on disk |

Implication: `budget.spent()` tracks the Sonnet transport + your own tokens, **not** the external models' tokens (those are subscription, off-meter). So a shim-routed DAG is cheap on the token budget but expensive on **wall-clock** (each node is a 3-8 min CLI run) and on **provider rate-limit headroom**. Size fan-out by provider headroom, never by `budget` (`SKILL.md` §Scale).

## 5. The filesystem bridge

The Workflow JS sandbox has **no filesystem**. The shim subagents do (they run Bash, and the CLI beneath them reads/writes freely). So inter-node data flows through `/tmp/dag-<task>/` files, and the workflow script passes only **path strings**:

```
node A prompt: "...WRITE result to /tmp/dag-x/spec.md"     → CLI writes the file
node B prompt: "READ /tmp/dag-x/spec.md, then..."          → CLI reads it
workflow script: only ever sees the path strings; never the bytes
```

Two hard rules fall out:
1. **Write every node's prompt file up front** (in a Bash step before launch) — the sandbox can't create them at runtime.
2. **Every READ path must be some node's WRITE path**, and the DAG control-flow ordering (`await`/`pipeline`) must guarantee the writer runs before the reader. The data dependency lives in the path convention; the ordering lives in the JS. They must agree, or the reader node improvises/hangs.

Returning content through node return values is possible (the stdout IS returned) but reserved for tiny scalars — for any real artifact, files are the channel, and "filesystem-as-truth" verification after the run is mandatory (a completion return is not proof of a correct file).

## 6. Determinism, journaling & resume

Observed in the pilot transcript directory:

```
journal.jsonl                      ── the run's event journal (phases, agent starts/results)
agent-<id>.jsonl                   ── per-node full transcript (the shim command, Bash call, stdout)
agent-<id>.meta.json               ── per-node metadata (incl. agentType)
```

- **Persistence:** every `Workflow` invocation writes its script to a file and returns the path. Edit that file and re-invoke `Workflow({ scriptPath })` to iterate without resending.
- **Resume:** `Workflow({ scriptPath, resumeFromRunId })` replays the journal — the **longest unchanged prefix of `agent()` calls returns cached results instantly**; the first edited/new call and everything after runs live. Same script + same args → 100% cache hit. `TaskStop` the prior run before resuming. This is what makes fixing a late node cheap: the early nodes (each an expensive external-model run) are not re-paid.
- **Why the clock/RNG ban matters here:** caching keys on `(prompt, opts)`. If a script could call `Date.now()`/`Math.random()`, a replay would diverge from the journal and the cache would be unsound — so the sandbox forbids them. Stamp time after the workflow returns; vary agents by index, not RNG.

## 7. Concurrency & backpressure

- **Cap:** `min(16, cores-2)` concurrent `agent()` calls per workflow; excess queue and drain as slots free. Lifetime cap 1000 agents; a single `parallel`/`pipeline` call accepts ≤4096 items.
- **`pipeline` vs `parallel`:** `pipeline` has **no barrier** between stages (item A in stage 3 while B is in stage 1; wall-clock = slowest single-item chain) — the default. `parallel` **is** a barrier (await all; throws → `null`, never rejects) — use only when stage N needs ALL of stage N-1 (dedup, count-zero exit, cross-item compare).
- **The cap is not provider-aware.** It will run 16 Kimi nodes at once and trip Kimi's ~1-3 sustained concurrency. Throttle below the cap yourself: chunk items and `parallel` each chunk, or serialize a loop. The runtime backpressure protects the *host*, not the *provider* — that's your job (`SKILL.md` §Scale).

## 8. Failure & isolation

- **Node failure** (the shim errors, the stage callback throws) resolves that item to `null` in `parallel`/`pipeline` results — `.filter(Boolean)` and re-dispatch. The workflow does not abort on one node.
- **Stall** (MiniMax): the node returns *successfully* but empty (a `step_start`, no `text` part). It is NOT an exception — detect it by parsing the return (`textOf(...) === ''`) and retry the SAME model ≤3×, no reroute.
- **Worktree isolation:** `agent(..., { isolation: 'worktree' })` runs a node in a fresh git worktree — expensive (~200-500ms + disk), only for nodes that mutate files in parallel and would otherwise conflict. Most shim DAGs hand off through `/tmp` and don't need it.
- **Judgment isolation:** the runtime *cannot* call back to Opus mid-run, so any cross-node judgment is structurally forced to a segment boundary (one `Workflow` call per segment, Opus synthesis between). This is a feature — it keeps synthesis inline where it belongs.

## 9. Visibility planes

- **Plane 1 — `/workflows`** (and the launch result + completion `<notification>`): the DAG's live progress — phase groups, per-node label rows, the final `return` value and usage summary. This is the Claude-Code-native view of the orchestration.
- **Plane 2 — shim run records:** each shim invocation logs a `"source":"shim"` record (`event`: `started`/`finished`) and emits a final `SHIM-DONE exit=<n>` sentinel; the absence of the sentinel signals clipped or still-running output. The DAG layer inherits this for free because nodes route through the shims.

A node that leaked to a default subagent appears in Plane 1 (as a generic agent row) but **NOT** with shim records or the `SHIM-DONE` sentinel — a second, independent way to spot a leak after the fact.

## 10. Layering — who owns what

```
subagent-model-routing Part A       ── DAG topology, node=agentType-routed-helper, segmentation,
  (this doc)                  filesystem handoff, anti-leak gate, the Workflow substrate
        │ shares transport with ▼
subagent-model-routing Part B       ── model catalog/picking, response parsing, auth pre-flight, failure modes,
  (SKILL.md Part B (flat dispatch & shared transport substrate))       suppression-cheat, per-provider headroom, Why-Sonnet, cost/quota
        │ drives ▼
plugins/subagent-model-routing-claude/agents/{codex,opencode}-shim.md ── the Sonnet transport agent contracts (find-command → Bash → verbatim)
        │ exec ▼
~/.claude/scripts/*-shim.sh ── thin wrappers installed by scripts/install.sh from the bundled scripts/
        │ supervise ▼
codex / opencode CLI        ── agentic harness around the external model
```

The cut is clean: this skill never re-derives anything below the dashed line. If a node misbehaves because of *transport* (auth, parsing, stalls, rate), the fix is in Part B's shared transport layer; the DAG is correct once transport is.

## 11. Verified-findings log

- **Pilot run** (2-node DAG, codex → kimi, fs handoff, ~39s, 2 agents): `agentType` routing inside a `Workflow` is **real** — transcripts show `codex-shim.sh …` / `opencode-shim.sh kimi-for-coding/k2p7 …` actually invoked, shim `agentType` values in `agent-*.meta.json` (namespaced as `"subagent-model-routing-claude:codex-shim"` / `"subagent-model-routing-claude:opencode-shim"`), fingerprints `gpt-5.4-mini`/`kimi-for-coding`, no default subagents. Filesystem handoff works cross-model (kimi read codex's `spec.md`, wrote `impl.js`). Mechanical-edge ordering held (`await` sequenced spec before impl). Journaling files (`journal.jsonl`, `agent-*.jsonl`, `agent-*.meta.json`) confirmed present.
- **Empirical** — the export-strip/async-wrap transform (§2): confirmed by `node --check` failing raw templates ("'return' outside of function") and passing after the wrap; all `SKILL.md` scripts pass the transform-then-check gate.

## 12. File map (the DAG stack, one line each)

- `plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md` — operational skill (flat dispatch + DAG orchestration).
- `plugins/subagent-model-routing-claude/skills/subagent-model-routing/ARCHITECTURE.md` — this file (DAG mechanism/internals).
- `plugins/subagent-model-routing-claude/commands/dag-routing.md` — `/subagent-model-routing-claude:dag-routing <task>` command stub (also a Workflow opt-in).
- `plugins/subagent-model-routing-claude/agents/{codex,opencode}-shim.md` — Sonnet transport agent contracts.
- `~/.claude/scripts/{codex,opencode}-shim.sh` — shim wrappers installed from `scripts/` by `scripts/install.sh`.
- Workflow tool — `agent()`/`pipeline()`/`parallel()`/`phase()`/`log()`/`budget`/`args`/`workflow()`, `agentType`, `resumeFromRunId`/`scriptPath`.
