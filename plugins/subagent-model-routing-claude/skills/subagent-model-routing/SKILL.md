---
name: subagent-model-routing
user-invocable: false
description: Route work to non-Claude models (codex/GPT-5.x, Kimi, xAI Grok 4.5, GLM, MiniMax, and local models through opencode custom providers) over the codex/kimi/opencode/grok standalone shims. Supports both one-shot flat dispatch and dependency-ordered DAG orchestration via the Workflow tool. Use when delegating authoring, review, analysis, throughput, or multi-step work to external agentic CLI harnesses. Section 0 decides flat vs DAG; Picking the model decides which model.
---

# Model Routing

You are the orchestrator. This one skill covers both ways to delegate work to non-Claude models; section 0 picks the mechanism, and Picking the model picks the model. Both paths use the same standalone shim substrate and the same public ledger contract.

- **Flat dispatch**: independent, one-shot units, no dependency edges. Fire `Agent({subagent_type:'subagent-model-routing-claude:codex-shim'|'subagent-model-routing-claude:kimi-shim'|'subagent-model-routing-claude:opencode-shim'|'subagent-model-routing-claude:grok-shim'})` calls directly. See Part B.
- **DAG orchestration**: dependency edges such as A->B, fan-out that is ordered/collected, or staged processing. Use the Workflow tool, with each node routed through `agentType`. See Part A.

## Picking the model (shared -- both mechanisms)

**Seed rankings** -- an example roster; maintain yours via `/subagent-model-routing-claude:distill`.

<!-- LEDGER:RANKINGS START (maintained by /subagent-model-routing-claude:distill -- edit via distill, not by hand) -->
**Current tiers (seed example -- maintain via `/subagent-model-routing-claude:distill` and your own ledger; last distilled 2026-07-09 (seed)):** codex GPT-5.6 Sol (provisional flagship seat) >= GLM-5.2 > Kimi K2.7 > MiniMax-M3. Seats: GLM = default author; GPT-5.6 Sol = hardest/critical + deepest review; Kimi = mid-tier/burst; MiniMax = throughput. Grok 4.5, GPT-5.6 Terra, and GPT-5.6 Luna remain unranked pending local evidence. Per-model detail: `ledger/*.md`.
<!-- LEDGER:RANKINGS END -->

**The test:** use the cheapest model/effort that can notice when it is wrong. A model running inside an agentic shim can read files, write files, run checks, and iterate. A plain completion cannot, so it needs either a trivially verifiable task or a stronger model plus an explicit verify step.

**The noticer must be deterministic.** "Can notice when it is wrong" means a real gate: typecheck, lint, tests, validators, or static detectors. Model cross-review can supplement the gate, but it never replaces it.

**The flow:**

1. Mechanically checkable work (format, rename, extract, classify) goes to the cheapest reliable route or to a script/template.
2. Work that reads several files and changes code defaults to GLM-5.2 through opencode; use Grok 4.5 or Kimi K2.7 for independent candidates until local evidence earns Grok a fixed seat.
3. User-visible breakage risk escalates to codex and must include a deterministic gate.
4. Auth, money, data loss, security, migrations, concurrency, and production infrastructure stay high-effort and high-gate; the critical synthesis stays inline.
5. Broad discovery fans out across cheaper routes, then the orchestrator synthesizes.
6. Ambiguous judgment should not be over-parallelized. Use the strongest route or keep it inline.

**Two axes, kept separate:**

- **External work-model**: codex, Grok, Kimi, GLM, MiniMax, or a local/self-hosted model exposed through opencode.
- **Claude node-model**: the transport node is Sonnet. Do not use Haiku for any content-bearing shim node.

The detailed seed roster and per-task routing table are in Part B.

## Prompt Reference Cards (shared -- both mechanisms)

The canonical host-filtered transport/model inventory is generated from `config/provider-registry.json` and bundled at [`references/routes.generated.md`](references/routes.generated.md). It intentionally omits Claude because Claude work stays native in this host; the prose below owns routing judgment and prompt construction rather than duplicating the machine-readable inventory.

These cards are compact runtime summaries. (Model tiers and capability cards, by contrast, are ledger-maintained seeds — see §The ledger.) For non-trivial prompts, high-stakes tasks, broad fan-out, or reusable templates, load the linked package-local reference section first.

If your CLI has MCP tools configured, prompts may direct their use.

### codex / GPT

- **Use for:** strongest implementer in the seed roster; hardest units, deepest review.
- **GPT-5.6 routes:** current Codex runtime model IDs are Sol (`gpt-5.6-sol`), Terra (`gpt-5.6-terra`), and Luna (`gpt-5.6-luna`). The system card defines Sol as flagship, Terra as capable and lower cost, and Luna as fastest and most cost-efficient.
- **Prompt shape:** include Goal, Context, Constraints, Completion Criteria, exact files, allowed edits, validation commands, and done criteria.
- **Authorization boundary:** state what may be changed, which destructive actions are forbidden or require confirmation, and what must remain untouched. GPT-5.6 system-card evaluations found a greater tendency than GPT-5.5 to go beyond user intent.
- **Verification:** name deterministic checks in the prompt and inspect the actual artifacts. A completion claim is not proof, especially after tool failures.
- **Reasoning control:** use the cheapest effort that can notice failure; raise effort only when the task needs it.
- **Gotcha:** do not omit validation criteria. Codex becomes much more reliable when it can prove its own work.
- Full reference: `references/model-prompting.md#openai-gpt-56-through-codex`

### xAI / Grok

- **Use for:** coding, agentic, and knowledge work through the Grok Build harness; keep it provisional in the roster until the local ledger supports a ranked seat.
- **Route:** `grok-shim.sh` defaults to `grok-4.5` and accepts `-m`/`--model` overrides.
- **Prompt shape:** state objective, repository context, scope and authorization boundaries, requested work, deterministic validation, and completion criteria.
- **Verification:** inspect the resulting artifacts and rerun decisive checks; the harness is agentic, but its completion report is still only a receipt.
- **Reasoning control:** Grok 4.5 defaults to `high`; use `--effort low` or `--effort medium` for routine, tightly scoped work.
- **Security:** Grok Build's sandbox is off by default. Forward `--sandbox workspace` when isolation is required; set `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0` if approvals should not be auto-accepted.
- Full reference: `references/model-prompting.md#xai-grok-45-through-grok-build`

### Kimi / Moonshot

- **Use for:** mid-tier authoring, parallel candidates, subscription-friendly burst work.
- **Prompt shape:** be explicit and detailed; use delimiters for source/context; define steps; provide complete examples for style or output shape.
- **Tool-use caveat:** in this repo's shim path, opencode owns tool exposure. Keep the task prompt focused on the work and output contract.
- **Reliability:** pilot new templates before fan-out.
- **Gotcha:** grounded review depends on the agentic harness reading real files. Do not use a non-tool completion route for review.
- Full reference: `references/model-prompting.md#kimi`

### GLM / Z.ai

- **Use for:** default routed authoring and review; balanced throughput and structured tasks.
- **Prompt shape:** define role/system behavior, use delimiters, specify output format, and split complex tasks into simple subtasks.
- **Reasoning control:** use explicit thinking controls when available instead of relying on phrasing.
- **Structured output:** through the shim, still demand parseable JSON when needed and validate it after return.
- **Gotcha:** coding-plan traffic uses the provider/model selected in the opencode command; do not duplicate endpoint details in prompts.
- Full reference: `references/model-prompting.md#glm`

### MiniMax

- **Use for:** throughput work when a Sonnet-grade route is enough; stall-retry policy applies.
- **Prompt shape:** use structured prompting: clear role, task, constraints, success criteria, and output shape.
- **Coding behavior:** allow or request a planning phase when that helps the task.
- **Thinking control:** `--thinking` is a binary visibility toggle for M3, not an effort dial.
- **Gotcha:** MiniMax can stall with no text before the sentinel. Retry the same model up to 3 times; do not silently reroute.
- Full reference: `references/model-prompting.md#minimax`

### Qwen / Alibaba

- **Route status:** routes through opencode as a custom provider (see README: routing a local model).
- **Use for:** Qwen-specific prompt experiments and independent candidate/review passes when your opencode installation exposes a Qwen-compatible route.
- **Prompt shape:** Qwen's official guide centers Context, Objective, Style, Tone, Audience, and Response. Add output examples, explicit steps, and high-recognizability separators for complex prompts.
- **Thinking control:** Qwen3 supports thinking controls; use thinking for complex reasoning and disable it for latency-sensitive work.
- **Gotcha:** this package has no dedicated Qwen transport. Expose the model through opencode and route it with `opencode-shim`.
- Full reference: `references/model-prompting.md#qwen`

---

## The ledger (observation-driven across sessions)

The ledger keeps routing opinions from freezing into folklore. It has two tiers, with one-way flow: hot -> warm.

- **Hot -- machine-local observations.** `~/.claude/subagent-model-routing/ledger/observations.jsonl`, append-only JSONL. The repo-installed shims log quantitative records automatically with `"source":"shim"`: `event:"started"` at dispatch start and `event:"finished"` at terminal with `model`, `wall_s`, `exit`, and `outcome`. Override the path with `SUBAGENT_MODEL_ROUTING_LEDGER`.
- **Warm -- repo-committed knowledge.** `ledger/{claude-fable-5,claude-opus-4.8,claude-sonnet-5,codex,grok,glm,kimi,minimax,qwen}.md` capability cards plus the marked rankings block at the top of Picking the model. The three Claude cards record Codex/Copilot-only shim targets; this Claude-hosted skill still uses native `Agent` calls for Claude work. These are seed examples -- maintain them via `/subagent-model-routing-claude:distill` and your own ledger.

Distill counts finished shim records for quality/rate math; started records are for orphan visibility.

**Qualitative records are the orchestrator's job.** The shim already wrote the quantitative line; it cannot know whether the result was notable. After a dispatch with a notable outcome (failure, surprise, tier-breaking quality, stall, clipped run), append one qualitative line:

```bash
printf '%s\n' '{"ts":"'"$(date -u +%Y-%m-%dT%H:%M:%S)"'","project":"<repo>","shim":"<shim>","model":"<model>","task_kind":"<author|review|extract|...>","outcome":"<ok|clipped|stall|error|timeout>","note":"<one sentence>","source":"orchestrator"}' >> "${SUBAGENT_MODEL_ROUTING_LEDGER:-$HOME/.claude/subagent-model-routing/ledger/observations.jsonl}"
```

Nothing notable means no entry. Distill with `/subagent-model-routing-claude:distill`.

---

## Part A -- DAG orchestration (dependency edges -> the Workflow tool)

Use this part when a task is multi-step with dependencies and you want the actual work delegated to non-Claude models. It fuses two capabilities:

- **The Workflow tool**: deterministic DAG orchestration with `agent()`, `pipeline()`, `parallel()`, `phase()`, and resume.
- **The shims**: `codex-shim` routes GPT work through codex; `kimi-shim` routes Kimi through Kimi Code; `grok-shim` routes Grok 4.5 through Grok Build; `opencode-shim` routes GLM, MiniMax, and custom/local providers through opencode. They run the CLI and return stdout verbatim.

Invoking this skill is authorization to call the Workflow tool for this task.

Two leaks must be prevented:

| # | Leak | What it looks like | Gate |
|---|---|---|---|
| 1 | Transport leak | A dependency graph is run through direct `Agent` or shell calls instead of Workflow. The models may run, but the DAG did not exist. | Section 0 |
| 2 | Node leak | The Workflow runs, but a node lacks `agentType` and executes as a default Claude subagent. | The anti-leak gate |

## Section 0 -- Mechanism is mandatory

**Step 0: is this actually a DAG?** A DAG has dependency edges: A->B, staged/ordered processing, a mechanical reduce that needs upstream outputs, a resume boundary, or a point where the orchestrator must judge/synthesize before downstream work.

- **No edges:** flat, independent, one-shot dispatch. Do not build a Workflow. Use Part B.
- **Has edges:** use `Workflow({ scriptPath })`. Do not run a DAG as direct `Agent({subagent_type:'subagent-model-routing-claude:codex-shim'|'subagent-model-routing-claude:kimi-shim'|'subagent-model-routing-claude:opencode-shim'|'subagent-model-routing-claude:grok-shim'})` calls, direct shell invocations, or inline work.

Fan-out alone is width, not depth. If each unit has an internal `spec -> build` edge, the whole thing is a DAG even when units are independent. Conversely, do not invent stages: a single agentic shim node already authors, verifies, and fixes within its own loop.

The node string `Run verbatim: ~/.claude/scripts/codex-shim.sh ...` is byte-identical in flat dispatch and DAG nodes. The Workflow wrapper is what makes it a DAG node.

Once inside Workflow, every work node routes to a shim via `agentType`. A bare `agent(prompt)` is a bug.

## Pre-flight -- prove routing before you build

Run a small Workflow pilot on a fresh machine, a new setup, or any time you doubt wiring.

```js
export const meta = { name: 'dag-pilot', description: 'prove shim routing inside Workflow',
  phases: [{ title: 'Pilot' }] }
const codex = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/codex-shim.sh ${file}`, { agentType: 'subagent-model-routing-claude:codex-shim', model: 'sonnet', ...o })
const grok  = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/grok-shim.sh ${file}`, { agentType: 'subagent-model-routing-claude:grok-shim', model: 'sonnet', ...o })
const kimi  = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/kimi-shim.sh ${file}`, { agentType: 'subagent-model-routing-claude:kimi-shim', model: 'sonnet', ...o })
phase('Pilot')
const [g, x, k] = await parallel([
  () => codex('/tmp/dag-pilot/pong.md', { label: 'codex-pong', phase: 'Pilot' }),
  () => grok('/tmp/dag-pilot/pong.md', { label: 'grok-pong', phase: 'Pilot' }),
  () => kimi('/tmp/dag-pilot/pong.md', { label: 'kimi-pong', phase: 'Pilot' }),
])
return { g, x, k }
```

Stage it and launch:

```bash
mkdir -p /tmp/dag-pilot
printf 'Reply with exactly: pong\n' > /tmp/dag-pilot/pong.md
# write the script above to /tmp/dag-pilot/pilot.mjs, then launch Workflow({ scriptPath: '/tmp/dag-pilot/pilot.mjs' })
```

When it completes, confirm the nodes routed to the shims by inspecting the run transcript directory:

```bash
TD=<transcript-dir-from-the-Workflow-launch-result>
grep -rhoE '~?/[^ "]*(codex|kimi|opencode|grok)-shim\.sh[^"\\]*' "$TD" | sort -u
grep -rhoE '"agentType":"[^"]*"' "$TD" | sort | uniq -c
grep -rhoE '(gpt-5|grok-4\.5|kimi-for-coding)' "$TD" | sort | uniq -c
```

Rows showing `subagent-model-routing-claude:codex-shim`, `subagent-model-routing-claude:kimi-shim`, `subagent-model-routing-claude:grok-shim`, and `subagent-model-routing-claude:opencode-shim`, plus the shim commands in transcripts, prove routing end-to-end. If routing is broken, stop and fix it before fan-out. A direct Part B dispatch is only an acknowledged stopgap for a flat task or for auth probing.

## Architecture in one paragraph

Express the task as a Workflow DAG. Each work node is an `agent()` call whose `agentType` is `subagent-model-routing-claude:codex-shim`, `subagent-model-routing-claude:kimi-shim`, `subagent-model-routing-claude:grok-shim`, or `subagent-model-routing-claude:opencode-shim`, so the node's work runs inside an external agentic CLI harness. Nodes hand off through the filesystem. You write every prompt file up front, launch the workflow, and synthesize raw returns or file artifacts inline after the run. Judgment edges split the workflow into segments.

## How a node routes to a model

A DAG node is an `agent()` call carrying `agentType`:

```js
agent("Run verbatim: ~/.claude/scripts/codex-shim.sh /tmp/dag-x/n1.md",
      { agentType: "subagent-model-routing-claude:codex-shim", model: "sonnet" })
```

- **No `schema`.** You want the shim's raw stdout, not a structured object forced by the Workflow layer. Prefer filesystem artifacts for structured output.
- **`agentType` carries the shim system prompt** into the node.
- **The names are namespaced.** Use `subagent-model-routing-claude:codex-shim`, `subagent-model-routing-claude:kimi-shim`, `subagent-model-routing-claude:grok-shim`, and `subagent-model-routing-claude:opencode-shim`. A bare shim name or a typo can leak to a default node.
- **Argument shape differs:** `codex-shim.sh <file> [flags]`; `kimi-shim.sh <file> [flags]`; `grok-shim.sh <file> [flags]`; `opencode-shim.sh <provider/model> <file> [flags]`.

Author nodes only through helpers. Keep helper definitions on one line so the audit can match them:

```js
export const meta = { name: 'dag-task', description: 'example DAG',
  phases: [{ title: 'Spec' }, { title: 'Build' }] }

const DIR = '/tmp/dag-task'

const codex   = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/codex-shim.sh ${file}`, { agentType: 'subagent-model-routing-claude:codex-shim', model: 'sonnet', ...o })
const grok    = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/grok-shim.sh ${file}`, { agentType: 'subagent-model-routing-claude:grok-shim', model: 'sonnet', ...o })
const kimi    = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/kimi-shim.sh ${file}`, { agentType: 'subagent-model-routing-claude:kimi-shim', model: 'sonnet', ...o })
const glm     = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/opencode-shim.sh zai-coding-plan/glm-5.2 ${file}`, { agentType: 'subagent-model-routing-claude:opencode-shim', model: 'sonnet', ...o })
const minimax = (file, o = {}) => agent(`Run verbatim: ~/.claude/scripts/opencode-shim.sh minimax/MiniMax-M3 ${file}`, { agentType: 'subagent-model-routing-claude:opencode-shim', model: 'sonnet', ...o })

phase('Spec')
const spec = await codex(`${DIR}/n1-spec.md`, { label: 'spec', phase: 'Spec' })

phase('Build')
const built = await parallel(UNITS.map((u) =>
  () => kimi(`${DIR}/n2-${u}.md`, { label: `impl:${u}`, phase: 'Build' })))

return { spec, built }
```

All helpers are peers. `codex` routes GPT work, `kimi` routes Kimi Code, `grok` routes Grok Build, and `glm`, `minimax`, and any local/custom provider route through opencode by changing the provider/model string. The model identity is chosen in the shim command or the provider's configured default, not by the Workflow node.

**Node model policy:** set `model: 'sonnet'` on every transport helper. Haiku is not reliable for content-bearing transport.

## The Workflow substrate -- mechanics you must know

- `meta` must be the first statement and a pure literal.
- The script is transformed before it runs; top-level `await` and `return` are legal in Workflow even though raw `node --check` needs a wrapper.
- The script has no filesystem, clock, or random APIs. The shim subagents do filesystem work.
- Use `phase(title)`, `log(msg)`, `agent(prompt, opts)`, `pipeline(items, ...stages)`, `parallel(thunks)`, `args`, `budget`, and one-level nested `workflow(...)` when needed.
- `pipeline` has no barrier between stages; `parallel` is a barrier.
- Concurrency is not provider-aware. Cap fan-out yourself.
- The Workflow call returns a run id and persisted script path. Edit that path and resume when needed.
- The final `return` is what Workflow hands back to you.

## The default node shape -- one self-verifying node per unit

An agentic shim node runs a full agent loop: read source, author, run gates, fix, and report. The default unit of work is one node, not `build -> review -> fix`.

Use a separate adversarial review node only for critical/contract units or when the user explicitly asks for independent review. Keep review off the per-unit critical path when possible: run builds in parallel, then one review-all node, then inline triage.

## The DAG-shape catalog

Pick the shape, then route every work node through a helper.

### Single node

```js
export const meta = { name: 'dag-one', description: 'single delegated node', phases: [{ title: 'Do' }] }
// helpers required
phase('Do')
const out = await codex('/tmp/dag-one/n1.md', { label: 'do', phase: 'Do' })
return { out }
```

### Fan-out (barrier) -- N independent nodes, collect all

```js
export const meta = { name: 'dag-fanout', description: 'N independent nodes, collected', phases: [{ title: 'Map' }] }
// helpers required
phase('Map')
const results = await parallel(UNITS.map((u) =>
  () => glm(`/tmp/dag-fanout/n-${u}.md`, { label: `unit:${u}`, phase: 'Map' })))
return { results: results.filter(Boolean) }
```

### Pipeline (no barrier) -- each item flows through stages independently

```js
export const meta = { name: 'dag-pipe', description: 'per-unit spec -> build, no barrier',
  phases: [{ title: 'Spec' }, { title: 'Build' }] }
// helpers required
const built = await pipeline(UNITS,
  (u) => codex(`/tmp/dag-pipe/spec-${u}.md`, { label: `spec:${u}`, phase: 'Spec' }),
  (_specOut, u) => kimi(`/tmp/dag-pipe/build-${u}.md`, { label: `build:${u}`, phase: 'Build' }))
return { built }
```

### Diamond / map-then-mechanical-reduce

```js
export const meta = { name: 'dag-diamond', description: 'spec -> N impls -> mechanical merge',
  phases: [{ title: 'Spec' }, { title: 'Build' }, { title: 'Merge' }] }
// helpers required
phase('Spec')
const spec = await codex('/tmp/dag-diamond/spec.md', { label: 'spec', phase: 'Spec' })
phase('Build')
const parts = await parallel(UNITS.map((u) =>
  () => glm(`/tmp/dag-diamond/build-${u}.md`, { label: `build:${u}`, phase: 'Build' })))
phase('Merge')
const merged = await codex('/tmp/dag-diamond/merge.md', { label: 'merge', phase: 'Merge' })
return { spec, parts: parts.filter(Boolean), merged }
```

### Loop-until-budget (scale depth to a token target)

```js
export const meta = { name: 'dag-loop', description: 'accumulate until budget runs low', phases: [{ title: 'Round' }] }
// helpers required
phase('Round')
const found = []
let i = 0
while (budget.total && budget.remaining() > 60000) {
  const r = await kimi(`/tmp/dag-loop/round-${i}.md`, { label: `round:${i}`, phase: 'Round' })
  found.push(r)
  i++
  log(`round ${i} done`)
}
return { rounds: found.length, found }
```

### Build -> review-all -> inline triage

```js
export const meta = { name: 'dag-build-review', description: 'parallel builds -> one review-all -> inline triage',
  phases: [{ title: 'Build' }, { title: 'Review' }] }
// helpers required
phase('Build')
const builds = await parallel(UNITS.map((u) =>
  () => glm(`/tmp/dag-build-review/build-${u}.md`, { label: `build:${u}`, phase: 'Build' })))
phase('Review')
const review = await codex('/tmp/dag-build-review/review-all.md', { label: 'review-all', phase: 'Review' })
return { builds: builds.filter(Boolean), review }
```

Write `review-all.md` so it iterates file-by-file and reports one findings section per artifact. If one review node would exceed the timeout, split the review by slices.

## Edges: mechanical vs judgment

A Workflow cannot call back to you mid-run. A dependency edge is one of two kinds:

- **Mechanical edge:** B's input is a deterministic function of A's output. Keep it inside the Workflow with `await`, `pipeline`, or `parallel`.
- **Judgment edge:** B's prompt needs you to evaluate, synthesize, or choose among A's outputs. Split the workflow there.

One Workflow call covers one dependency segment between judgment points.

Mechanical verification is not a judgment point. Typecheck/test/lint ordering belongs inside the same DAG unless you need cross-artifact synthesis.

## Extracting parallelism -- decompose on build-time edges

Parallelism comes from independent authoring units. Decompose on what a unit needs to compile and edit, not on the runtime dataflow the finished system will execute.

- **Parallel set:** units whose build-time dependencies are already present and whose file writes are disjoint.
- **Sequential set:** units with real code-import edges or shared-file writes.

A shared convention is a contract, not a dependency. Put the exact convention in every relevant prompt and verify afterward.

## Delegate the whole graph -- glue is nodes, not orchestrator work

When the mandate is "delegate everything," encode the whole reversible graph as nodes:

- Authoring and adversarial review.
- Integration/build/wiring nodes that read authored artifacts, edit shared registration files, and run gates.
- Branch work that is reversible.

Dispatched models must not run `git add` or `git commit`. They edit files only; the orchestrator reviews and commits.

Stays inline: cross-artifact synthesis, PRs, deploys, production registration, and any irreversible action.

## Handoff: filesystem-as-truth + write prompt files up front

The Workflow script has no filesystem, but shim subagents do. Pass paths by convention:

- Pick a run dir such as `/tmp/dag-<task>`.
- Node A writes `${DIR}/artifact`; node B reads that path.
- The control flow guarantees order; the paths carry data.

Write prompt files before launch. Each prompt should include task, read paths, write paths, no-suppression rule, validation commands, and completion criteria.

```bash
mkdir -p /tmp/dag-feature
for u in forecast aviation tropical; do
  cat > /tmp/dag-feature/n2-${u}.md <<EOF
READ /tmp/dag-feature/n1-spec.md, then implement the ${u} module.
WRITE the result to /tmp/dag-feature/impl-${u}.ts.
Do not resolve typecheck or lint errors via @ts-expect-error, @ts-ignore, or eslint-disable directives.
Address the root cause. If blocked, leave the file failing and document the blocker in the file.
Return a one-line summary; the artifact on disk is the deliverable.
EOF
done
```

After the run, verify artifacts on disk:

```bash
ls -la /tmp/dag-feature/impl-*.ts
wc -l /tmp/dag-feature/impl-*.ts
```

## The anti-leak gate

**Layer 0 -- helpers only.** Nodes are created through `codex()`, `grok()`, `kimi()`, `glm()`, and `minimax()` helpers only.

**Layer 1 -- hard rule.** Every `agent(` call site must carry one of the namespaced `codex-shim`, `grok-shim`, or `opencode-shim` agent types.

**Layer 2 -- mechanical audit before launch.**

```bash
S=/tmp/dag-<task>/script.mjs
total=$(grep -cE '\bagent\(' "$S")
defs=$(grep -cE '^\s*const (codex|grok|kimi|glm|minimax) *=.*\bagent\(' "$S")
[ "$total" -eq "$defs" ] || { echo "LEAK: $total agent( sites but only $defs helper defs"; exit 1; }
types=$(grep -oE "agentType: *'[^']+'" "$S" || true)
bad=$(printf '%s\n' "$types" | grep -vE "^agentType: *'subagent-model-routing-claude:(codex|kimi|opencode|grok)-shim'$" || true)
[ -z "$bad" ] || { echo "LEAK: bad/non-namespaced agentType:"; printf '%s\n' "$bad"; exit 1; }
[ "$(printf '%s\n' "$types" | grep -c .)" -eq "$defs" ] || { echo "LEAK: missing agentType in helper"; exit 1; }
bad_models=$(grep -E '^\s*const (codex|grok|kimi|glm|minimax) *=.*\bagent\(' "$S" | grep -vE "model: *['\"]sonnet['\"]" || true)
[ -z "$bad_models" ] || { echo "LEAK: helper missing model: 'sonnet':"; printf '%s\n' "$bad_models"; exit 1; }
printf '%s\n' "$types" | sort | uniq -c
```

**Layer 3 -- red flags.**

| Thought | Reality |
|---|---|
| "I will just batch direct shim calls." | Transport leak. DAGs run through Workflow. |
| "This node is trivial." | Trivial work still routes through a shim helper. |
| "Synthesis can be one quick node." | Synthesis is a segment boundary and stays inline. |
| "The workflow can pick the model." | You choose the model in the helper command. |
| "A generic reviewer agent is fine." | Reviewer nodes route through a shim too. |

**Layer 4 -- Definition of Done.**

- The DAG is launched via `Workflow({ scriptPath })`.
- Every work node is created through a helper.
- All node prompt files exist before launch.
- Every read path is written by an upstream node.
- Judgment edges are segment boundaries.
- The current contract permits the namespaced codex, kimi, grok, and opencode shim agent types. The historical pilot below predates the dedicated Kimi transport.
- Artifacts are verified on disk after the run.

## Parsing node returns

Standalone shims run the CLIs in plain-text mode. They do not inject `--json`, there is no JSONL contract, and there is no stderr preamble to strip.

The node return is the CLI's human-readable stream. The reply is the text before the trailing sentinel line:

```js
const replyText = (stdout) => stdout.split('\n').filter((line) => !/^SHIM-DONE exit=\d+$/.test(line)).join('\n').trimEnd()
```

Prefer filesystem artifacts for anything structured. If a node should produce JSON, a patch, or a report, instruct it to write that artifact to disk and verify the file.

A MiniMax stall is empty output before `SHIM-DONE exit=<n>`. Retry the same model up to 3 times. Do not silently reroute.

## Picking the model per node

**Example roster (seed) -- maintain via `/subagent-model-routing-claude:distill` and your own ledger.**

| Node job | Route |
|---|---|
| First-draft authoring | `glm` through `subagent-model-routing-claude:opencode-shim`; `kimi` for burst/parallel candidates |
| Independent coding/agentic candidate | `grok` through `subagent-model-routing-claude:grok-shim`, provisional until local evidence ranks it |
| Deep one-off reasoning or critical verification | `codex` through `subagent-model-routing-claude:codex-shim` |
| Throughput or bulk classification | `minimax` through `subagent-model-routing-claude:opencode-shim`, pilot first |
| Balanced extraction/structured tasks | `glm` through `subagent-model-routing-claude:opencode-shim` |
| Adversarial code review | `codex` or `glm`, both through agentic shims |
| Cross-node synthesis | Not a node; stays inline |

For diversity at a judgment edge, fan out to different routes.

## Scale, cost & concurrency

A shim-routed DAG is wall-clock expensive: each node is both a Workflow agent and an external CLI run. Planning is about rate-limit headroom, endpoint capacity, and wall-clock, not Claude token cost.

- Workflow concurrency is not provider-aware. Cap fan-out yourself.
- Pilot N=1 before broad fan-out.
- Log width caps and retry policy.
- Failed nodes come back as `null`; filter, inspect, and re-dispatch only the failed units.
- MiniMax stalls are retried on MiniMax up to 3 times.

## Resume & iteration

- Every Workflow invocation persists its script path. Edit that file and re-run `Workflow({ scriptPath })`.
- Resume with `Workflow({ scriptPath, resumeFromRunId: '<prior runId>' })` when the unchanged prefix can be cached.
- Keep scripts deterministic; pass variation through `args`.

## Failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| Transcript shows a default Claude subagent | Missing or mistyped `agentType` | Route through helpers, run the audit, re-pilot. |
| Node ran on Haiku | Missing `model: 'sonnet'` | Pin Sonnet on every helper. |
| Workflow rejects `meta` | Non-literal or not first statement | Make `meta` the first pure literal. |
| Date/RNG error | Disallowed runtime API | Pass values through `args`. |
| `node --check` complains about top-level return | Checked raw script instead of transformed wrapper | Use the smoke-test wrapper. |
| Node returns empty before `SHIM-DONE exit=<n>` | MiniMax stall or upstream empty result | Retry MiniMax same model up to 3 times; otherwise inspect artifacts and exit code. |
| Missing `SHIM-DONE exit=<n>` | Clipped output or still-running child | Check the artifact on disk and split the unit or raise timeouts deliberately. |
| Input file absent | Prompt read/write path mismatch | Enforce every read path has an upstream write path. |
| Artifact missing or 0 bytes | Silent agent failure | Verify files and re-dispatch with tighter path instructions. |
| Rate-limit wave | Provider headroom exceeded | Chunk fan-out or switch failed units to a different route, except MiniMax stall policy. |
| Suppression directive added | Agent shortcut | Re-dispatch with the no-suppression rule and inspect the artifact. |
| Output copied the prompt exemplar | Prompt exemplar was skeletal | Use a complete real exemplar and pilot first. |

## All shims are agentic -- DAG implications

`opencode`, `codex`, and Grok Build run full agent loops inside a node: read source, author or quote, run gates, fix, and report.

- A single node already authors and verifies; do not add reflexive per-unit review/fix stages.
- One unit of work per node; split multi-unit prompts.
- A node needing more than the configured ceiling should be split, or the operator should deliberately raise `SHIM_TIMEOUT_SECS` and `BASH_MAX_TIMEOUT_MS`.
- Suppression-cheat risk survives into artifacts; inspect authored files.

## The boundary -- what stays inline with Opus

| Stays inline | Why |
|---|---|
| Cross-node synthesis / picking the best candidate | Synthesis is the intelligence work. |
| Choosing node models and writing prompts | The prompt is the artifact spec. |
| Schemas, type hierarchies, scoring methods | Wrong shape cascades. |
| DAG topology | The graph determines all downstream work. |
| Final integration review | Node gates are necessary, not sufficient. |

## Smoke test (always fresh)

```bash
mkdir -p /tmp/dag-pilot
printf 'Reply with exactly: pong\n' > /tmp/dag-pilot/pong.md
~/.claude/scripts/kimi-shim.sh /tmp/dag-pilot/pong.md | tail -n 1

S=/tmp/dag-pilot/pilot.mjs
total=$(grep -cE '\bagent\(' "$S")
defs=$(grep -cE '^\s*const (codex|grok|kimi|glm|minimax) *=.*\bagent\(' "$S")
[ "$total" -eq "$defs" ] && echo "audit OK" || echo "LEAK"

python3 - "$S" <<'PY'
import sys, subprocess, tempfile, os
b = open(sys.argv[1]).read().replace('export const meta', 'const meta')
p = os.path.join(tempfile.gettempdir(), 'wfchk.js')
open(p, 'w').write('async function f(){\n' + b + '\nreturn 0\n}\n')
r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
print('syntax OK' if r.returncode == 0 else 'syntax FAIL: ' + r.stderr.strip())
PY

# After the live pilot, inspect transcripts for the namespaced codex, kimi, grok, and opencode shim agent types.
```

## Provenance -- what's been verified

- **2026-06-15, run `wf_aefe2be3-052`**: a 2-node DAG (`codex` spec -> `kimi` implementation, filesystem handoff) executed via the Workflow tool. Verified end-to-end: `agentType` routed Workflow nodes to shim agents, transcripts showed `codex-shim.sh` and `opencode-shim.sh` invocations with `subagent-model-routing-claude:codex-shim` and `subagent-model-routing-claude:opencode-shim`, filesystem handoff worked, and mechanical ordering held.
- Static: embedded helper patterns pass the transform-then-`node --check` syntax gate and the leak audit.

## See also -- DAG layer

- `scripts/*.sh` in this repo: the public standalone shim scripts installed to `~/.claude/scripts/*-shim.sh`.
- `plugins/subagent-model-routing-claude/agents/{codex,kimi,opencode,grok}-shim.md`: transport agent definitions registered under their namespaced shim agent types.
- `plugins/subagent-model-routing-claude/commands/dag-routing.md`: Workflow entry command.
- `plugins/subagent-model-routing-claude/skills/subagent-model-routing/ARCHITECTURE.md`: architecture reference.
- `references/model-prompting.md`: self-contained runtime model prompting reference.

---

## Part B -- Flat dispatch & shared transport substrate

Use this part for independent one-shot dispatches with no dependency edges. The model roster, parsing, pre-flight, failure modes, and cost guidance are shared by flat dispatch and DAG nodes.

You are the orchestrator. You decide what work needs doing, which model is right, and how to dispatch. The shim subagents are transport pipes: they run one shell command through a CLI agentic harness and return stdout verbatim.

Active shims:

- **`codex-shim`** wraps the Codex CLI for GPT models.
- **`kimi-shim`** wraps the Kimi Code CLI for Kimi models.
- **`grok-shim`** wraps the Grok Build CLI and defaults to Grok 4.5.
- **`opencode-shim`** wraps opencode for GLM, MiniMax, and any custom provider configured in opencode.

There is no central router. Each CLI manages its own provider credentials and agent loop.

## Pre-flight (30-second probe)

```bash
echo "Reply with exactly: pong" > /tmp/pong.md

# Kimi Code transport health
~/.claude/scripts/kimi-shim.sh /tmp/pong.md

# codex transport health; optional when quota matters
~/.claude/scripts/codex-shim.sh /tmp/pong.md -c model_reasoning_effort=low

# Grok Build transport health; optional when quota matters
~/.claude/scripts/grok-shim.sh /tmp/pong.md --effort low

# auth surfaces
opencode auth list
kimi login
codex login
grok login
```

Use `opencode auth list` to check configured providers. Use `kimi login`, `codex login`, or `grok login` when the corresponding CLI reports an authorization failure; headless Grok Build can use `XAI_API_KEY`. Do not parse private auth files in this public skill.

## Architecture in one paragraph -- transport layer

Four CLIs, four harness families. Kimi Code handles Kimi routes through the user's Kimi CLI configuration. `opencode` handles GLM, MiniMax, and custom/local providers. `codex` handles GPT routes through the user's Codex CLI login. Grok Build handles Grok 4.5 through `grok` authentication or `XAI_API_KEY`. A flat dispatch spawns the matching Sonnet transport subagent, runs its standalone shim, and returns the CLI stream. The final line of a complete run is `SHIM-DONE exit=<n>`.

The shared installer also provides `~/.claude/scripts/model-routing` and private structured run records. Run `model-routing doctor` before first use or when provider/plugin drift is suspected; its default path performs no discovery. Use explicit `doctor --discover-models` only for a deliberate catalog refresh. For recovery, use `model-routing runs list`, `runs show <id>`, or `runs logs <id> --channel both`; no routing metadata may be appended after the sentinel. Prompt bodies are not retained by default. Add `--routing-retain-prompt` only when explicitly needed, and treat retained model output as potentially sensitive.

Claude's native Workflow tool remains the default and enforcement target for Claude-hosted DAGs. The shared `model-routing workflow run ... --host claude` runner is only for an explicitly requested external-only graph containing Codex, Kimi, Grok, or OpenCode tasks; it must never be used to route Claude through `claude-shim`. Its `--host` value is self-declared advisory metadata, so the existing tripwire hooks remain the actual enforcement layer.

For a Codex, Kimi, Grok, or OpenCode write task that must not touch Claude's caller worktree, add `--routing-workspace isolated --routing-task-mode write` to the shim invocation. Inspect with `model-routing runs diff <id>`, apply only after review with `runs apply <id> --target <repo>`, and remove the owned branch/worktree explicitly with `runs discard <id> --yes`. Claude work remains on native `Agent`/Workflow surfaces, and Claude's tripwire hooks remain the enforcement layer for those host-native paths.

## Picking the model

### Tier by artifact novelty

**Example roster (seed) -- maintain via `/subagent-model-routing-claude:distill` and your own ledger.**

| Tier | Examples | Dispatch pattern |
|---|---|---|
| Schema / shared contract / runtime selector | Direction records, token cascade rules, hooks | Inline; no dispatch |
| Novel layout / performance-sensitive / prose template | SVG math, mobile rendering paths, discriminated prose | Codex plus optional GLM candidate; synthesize inline |
| Composition of existing widgets | Most page templates and glue code | Codex or opencode autonomous-verify |
| Template scaffolding | Many schema-conformant entries from source files | Script/template first |
| Code review / verification | Session diff review, compliance audit | Codex or GLM through agentic shims |
| Test infrastructure | Smoke specs, ignored-pattern lists | Inline; quality decision |

### Allowed routes

**Example roster (seed) -- maintain via `/subagent-model-routing-claude:distill` and your own ledger.**

| Shim | Default route | Alternates |
|---|---|---|
| `subagent-model-routing-claude:kimi-shim` -> Kimi | configured Kimi default | override with `-m`/`--model` |
| `subagent-model-routing-claude:opencode-shim` -> GLM | `zai-coding-plan/glm-5.2` | routes listed by `opencode models` |
| `subagent-model-routing-claude:opencode-shim` -> MiniMax | `minimax/MiniMax-M3` | routes listed by `opencode models`; stall policy applies |
| `subagent-model-routing-claude:codex-shim` -> GPT | Codex CLI default | GPT-5.6 Sol: `gpt-5.6-sol`; Terra: `gpt-5.6-terra`; Luna: `gpt-5.6-luna` |
| `subagent-model-routing-claude:grok-shim` -> Grok | `grok-4.5` | override with `-m`/`--model`; effort is `low`, `medium`, or `high` |
| `subagent-model-routing-claude:opencode-shim` -> local/custom | any configured provider/model | use `opencode models` to find the route |

Refresh the opencode catalog with `opencode models`, Grok Build models with `grok models`, and Codex model assumptions from the Codex CLI documentation or `codex` help output. Keep roster changes as seed examples until your ledger supports them.

### Which to pick per task shape

**Example roster (seed) -- maintain via `/subagent-model-routing-claude:distill` and your own ledger.**

| Task shape | Route |
|---|---|
| Authoring narrative / first-draft TypeScript or frontend work | `subagent-model-routing-claude:opencode-shim` with GLM-5.2; `subagent-model-routing-claude:kimi-shim` as parallel candidate |
| Throughput / bulk classification | `subagent-model-routing-claude:opencode-shim` with MiniMax-M3, pilot first |
| Balanced extraction / structured tasks | `subagent-model-routing-claude:opencode-shim` with GLM-5.2 |
| Deep one-off reasoning / autonomous verification | `subagent-model-routing-claude:codex-shim` |
| Independent coding / agentic candidate | `subagent-model-routing-claude:grok-shim`, provisional until local evidence ranks it |
| Local/self-hosted model experiment | `subagent-model-routing-claude:opencode-shim` with the custom provider/model |
| Adversarial code review | `subagent-model-routing-claude:codex-shim` or GLM through `subagent-model-routing-claude:opencode-shim` |
| Claude-only work | regular Claude `Agent`, not a shim |

## MCP tools in dispatched CLIs

Dispatched CLIs may expose MCP tools the user configured.
Treat those tools as additive grounding, not a guaranteed dependency.
Keep pong probes tool-free.

## MiniMax stall handling

MiniMax can stall: the shim returns `SHIM-DONE exit=<n>` with no useful text before the sentinel. This is a provider/adapter observation, not a parsing failure.

Policy:

- A stall is empty text before the sentinel.
- Re-dispatch the same MiniMax route up to 3 times.
- If it still stalls, report the failure and stop; do not silently reroute to GLM or Kimi.

Check opencode's log directory only when you need provider diagnostics. The operational signal for dispatch is the text before `SHIM-DONE exit=<n>` plus the artifact on disk.

## Why all shims must wrap agentic harnesses

For code review or any task requiring accurate quotes from existing files, the model must run inside an agent harness with file-reading tools. Without tools, smart models invent plausible file:line citations. With tools, the model can inspect source and ground claims.

Prior project post-mortems showed the same lesson repeatedly: non-agentic completions are unsafe for grounded review; agentic shims are safe only when prompts require inspection and deterministic checks.

Operating rule:

- Review, verification, and bug-finding use codex, kimi, grok, or opencode shims.
- Authoring/generation can use any agentic shim, but must be verified by deterministic project gates.
- Bare non-tool completions are not a review route.

## Dispatch mechanics (async harness, 20-minute ceiling)

- Dispatches are launched through `Agent` with the namespaced codex, kimi, grok, or opencode shim type.
- Fire independent dispatches in one message when you need throughput.
- The complete result ends with `SHIM-DONE exit=<n>`.
- No sentinel means clipped output or a still-running child; check the artifact on disk before trusting the return.
- Keep each unit below the configured ceiling. If one unit cannot fit, split the unit, or deliberately raise both `SHIM_TIMEOUT_SECS` and `BASH_MAX_TIMEOUT_MS`.
- Do not background shell commands from a dispatch prompt.

## Dispatch pattern -- single call

1. Decide the route and effort flags.
2. Write the prompt to a file. File-based prompts are the robust default.
3. Dispatch through `Agent`.

Opencode:

```text
Agent({
  subagent_type: "subagent-model-routing-claude:opencode-shim",
  description: "review forecast module via GLM",
  prompt: "Run this exact command, return stdout verbatim, no summary, no interpretation:\n\n~/.claude/scripts/opencode-shim.sh zai-coding-plan/glm-5.2 /tmp/review-forecast.md"
})
```

Codex:

```text
Agent({
  subagent_type: "subagent-model-routing-claude:codex-shim",
  description: "implement parser via codex",
  prompt: "Run this exact command, return stdout verbatim, no summary, no interpretation:\n\n~/.claude/scripts/codex-shim.sh /tmp/author-parser.md"
})
```

Grok Build:

```text
Agent({
  subagent_type: "subagent-model-routing-claude:grok-shim",
  description: "implement parser via Grok 4.5",
  prompt: "Run this exact command, return stdout verbatim, no summary, no interpretation:\n\n~/.claude/scripts/grok-shim.sh /tmp/author-parser.md --effort high"
})
```

Notes:

- The `subagent_type` selects the transport.
- The `description` labels the row/notification.
- Extra Kimi Code flags forward after the prompt file: `~/.claude/scripts/kimi-shim.sh /tmp/p.md --model kimi-code/kimi-for-coding`.
- Extra opencode flags forward after the prompt file: `~/.claude/scripts/opencode-shim.sh zai-coding-plan/glm-5.2 /tmp/p.md --variant high --agent plan`.
- Extra codex flags forward after the prompt file: `~/.claude/scripts/codex-shim.sh /tmp/p.md -m gpt-5.6-sol -c model_reasoning_effort=low`.
- Extra Grok Build flags forward after the prompt file: `~/.claude/scripts/grok-shim.sh /tmp/p.md --effort medium --sandbox workspace`.

## Dispatch pattern -- parallel N (throughput priority)

1. Write all N prompts up front: `/tmp/task-001.md` through `/tmp/task-N.md`.
2. Dispatch all N Agent calls in one message.
3. For each result, split off the sentinel, inspect the text, and verify artifacts on disk.

Example:

```text
Agent({subagent_type: "subagent-model-routing-claude:opencode-shim", description: "extract 01",
       prompt: "Run verbatim: ~/.claude/scripts/opencode-shim.sh zai-coding-plan/glm-5.2 /tmp/extract-01.md"})
Agent({subagent_type: "subagent-model-routing-claude:opencode-shim", description: "extract 02",
       prompt: "Run verbatim: ~/.claude/scripts/opencode-shim.sh zai-coding-plan/glm-5.2 /tmp/extract-02.md"})
```

Partial failure:

- For rate-limit waves, chunk fan-out or switch failed units to another route.
- MiniMax stalls retry MiniMax only, up to 3 times.
- Keep provider headroom conservative until your own ledger proves higher concurrency.

## Default to parallel Kimi alongside codex when useful

For authoring jobs expected to take several minutes, a parallel Kimi candidate can give an independent implementation for inline synthesis:

```text
Agent({subagent_type: "subagent-model-routing-claude:codex-shim", description: "author via codex",
       prompt: "Run verbatim: ~/.claude/scripts/codex-shim.sh /tmp/feature-prompt.md"})
Agent({subagent_type: "subagent-model-routing-claude:kimi-shim", description: "author via Kimi",
       prompt: "Run verbatim: ~/.claude/scripts/kimi-shim.sh /tmp/feature-prompt.md"})
```

Skip the parallel candidate when the artifact is routine and deterministic gates are strong.

## Pilot before fan-out

For any new prompt template, dispatch N=1 first. Inspect output and artifacts. Check that the model did not copy placeholders from the prompt exemplar. Use complete real exemplars, not skeletons.

## Filesystem-as-truth

The completion text is a receipt, not the source of truth. After every authoring dispatch:

```bash
ls -la <expected-path>
wc -l <expected-path>
head -20 <expected-path>
```

For code, run the project gate. Missing, empty, or wrong-shape files are failures regardless of the summary.

## All shims wrap agentic harnesses -- implications

When dispatched, opencode, codex, and Grok Build can read the tree, write files, run commands, fix errors, and report completion.

- "Dispatch -> stage -> synthesize -> integrate" is often wrong: one agentic dispatch can author and verify.
- Suppression-cheat risk remains. Prompt against suppression directives and inspect artifacts.
- One unit of work per call.
- If a unit exceeds the ceiling, split it or deliberately raise `SHIM_TIMEOUT_SECS` and `BASH_MAX_TIMEOUT_MS`.

## The boundary -- what stays inline (transport restatement)

| Stays inline | Why |
|---|---|
| Picking model and shim | Strategic. |
| Writing prompt body | The prompt is the spec. |
| Designing schemas/type hierarchies/scoring | Cross-cutting. |
| Synthesizing across responses | Synthesis is judgment. |
| Final production wording | User-facing judgment. |
| Final integration review | Gate output still needs inspection. |
| Test infrastructure quality decisions | Determines whether gates matter. |

## Parsing the response

Standalone shims run CLIs in plain-text mode. Do not pass or expect injected JSON flags. Do not write jq recipes for shim output.

The complete output ends with:

```text
SHIM-DONE exit=<n>
```

The reply is everything before that final sentinel line:

```js
const replyText = (stdout) => stdout.split('\n').filter((line) => !/^SHIM-DONE exit=\d+$/.test(line)).join('\n').trimEnd()
```

If the sentinel is absent, treat the output as clipped or still running. Prefer artifacts on disk for structured data. For MiniMax, empty text before the sentinel is a stall; retry the same model up to 3 times.

## codex-shim model / effort overrides

The Codex CLI owns available model strings and effort flags. Typical forms:

```bash
~/.claude/scripts/codex-shim.sh /tmp/task.md -m gpt-5.6-sol -c model_reasoning_effort=low
~/.claude/scripts/codex-shim.sh /tmp/task.md --model=gpt-5.6-terra
~/.claude/scripts/codex-shim.sh /tmp/task.md -m gpt-5.6-luna
~/.claude/scripts/codex-shim.sh /tmp/task.md -c model_reasoning_effort=medium
```

Consult the Codex CLI help/docs for current model and effort names.

## grok-shim model / effort overrides

The shim defaults to `grok-4.5`. Grok Build accepts `-m`/`--model` and Grok 4.5 supports `--effort low|medium|high`; xAI documents `high` as the default.

```bash
~/.claude/scripts/grok-shim.sh /tmp/task.md --effort medium
~/.claude/scripts/grok-shim.sh /tmp/task.md --model=grok-4.5 --sandbox workspace
```

Scripted invocations automatically include `--no-auto-update`, `--no-alt-screen`, plain output, and the prompt via `-p`. In unrestricted mode the shim also passes `--always-approve`.

## opencode-shim profile overrides

opencode exposes provider/model routes via `opencode models`. It may also expose flags such as `--variant`, `--thinking`, and `--agent <name>` depending on version and provider.

Pass flags through after the prompt file:

```bash
~/.claude/scripts/opencode-shim.sh zai-coding-plan/glm-5.2 /tmp/p.md --variant high --agent plan
```

## MiniMax M3 thinking toggle

MiniMax M3 has a reasoning visibility toggle surfaced by opencode as `--thinking`. It is binary, not an effort dial. Leave it off for normal dispatch; turn it on only when the reasoning trace is itself useful.

## GLM empty-completion via opencode

Historical provider/adapter observation: older opencode builds could return no text for GLM despite a successful process exit. If GLM goes empty again, first upgrade opencode and rerun a small pong. If the route remains empty, switch the affected work to Kimi or codex and record the failure in the ledger.

## Why Sonnet, not Haiku

Transport agents use Sonnet because they must ferry long stdout faithfully. Haiku has historically truncated or stalled on content-bearing transport. The shim's job is not deep reasoning, but reliable byte transport still needs a robust Claude node.

## Failure modes -- transport layer

| Symptom | Likely cause | Action |
|---|---|---|
| `opencode` command not found | CLI missing | Install opencode and verify with `opencode --version`. |
| `opencode auth list` shows no usable providers | Provider login missing | Run `opencode auth login` for the needed providers. |
| `kimi` command not found | Kimi Code CLI missing | Install Kimi Code and verify with `kimi --version`. |
| Kimi Code authorization failure | Missing Kimi login | Run `kimi login`. |
| Codex authorization failure | Expired/missing Codex login | Run `codex login`. |
| `grok` command not found | Grok Build CLI missing | Install Grok Build and verify with `grok version`. |
| Grok Build authorization failure | Missing browser/device login or API key | Run `grok login`, `grok login --device-auth`, or set `XAI_API_KEY` for headless use. |
| GLM returns no text | opencode/provider adapter issue | Upgrade opencode, retry pong, then route failed work elsewhere if needed. |
| First run hangs during setup | CLI initializing local state | Wait briefly; rerun small pong. |
| Missing `SHIM-DONE exit=<n>` | Clipped output or still-running child | Check artifact on disk; split unit or raise `SHIM_TIMEOUT_SECS` and `BASH_MAX_TIMEOUT_MS`. |
| `SHIM-DONE exit=<n>` is present but artifact missing | Agent failed to write expected file | Re-dispatch with exact write path and verify. |
| Multi-unit prompt drops later units | Per-invocation context/turn cap | One unit per call. |
| Suppression directive added | Shortcut around gate | Re-dispatch with no-suppression instruction and inspect files. |
| Reviewer hallucinates file lines | Non-agentic route used | Use codex, kimi, grok, or opencode shims with file inspection. |
| Routed model ignores optional MCP instruction | Tool not configured in that CLI | Treat MCP as additive; reroute only if the task requires that tool. |

## Observability (optional)

The ledger JSONL is the quantitative record for every dispatch (`started`/`finished` with `wall_s`, `exit`, and `outcome`). Users with an OTLP collector can set `OPENCODE_OTLP_ENDPOINT` for OpenCode spans and standard `OTEL_*` environment variables for Codex spans; the shim appends `gen_ai.request.model` for per-dispatch attribution. See the root `README.md` `## Observability` section for setup. A localhost example is `http://localhost:4318`.

## Cost / quota

Use whatever subscriptions/endpoints your CLIs are authenticated to. Planning is about rate limits, endpoint capacity, and wall-clock. Failed retries cost time even when they do not cost per-call money, so track success rate and pivot to scripts/templates when dispatch is not paying off.

## Smoke test -- transport layer

```bash
echo "Reply with exactly: pong" > /tmp/pong.md
opencode auth list
~/.claude/scripts/kimi-shim.sh /tmp/pong.md | tail -n 1
~/.claude/scripts/codex-shim.sh /tmp/pong.md -c model_reasoning_effort=low | tail -n 1
~/.claude/scripts/grok-shim.sh /tmp/pong.md --effort low | tail -n 1
opencode models
grok models
```

Expected complete shim output ends with `SHIM-DONE exit=<n>`.

## See also

- `scripts/codex-shim.sh`, `scripts/kimi-shim.sh`, `scripts/opencode-shim.sh`, and `scripts/grok-shim.sh` in this repo.
- `plugins/subagent-model-routing-claude/agents/{codex,kimi,opencode,grok}-shim.md`.
- `plugins/subagent-model-routing-claude/skills/subagent-model-routing/ARCHITECTURE.md`.
- `references/model-prompting.md` for the self-contained runtime model reference.
- `plugins/subagent-model-routing-claude/README.md` for installation and custom-provider routing.
