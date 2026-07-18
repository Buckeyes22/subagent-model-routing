# Run records

Every accepted dispatch receives a UUID before provider preflight and writes a private run directory:

```text
${SUBAGENT_MODEL_ROUTING_STATE_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/subagent-model-routing}/runs/<dispatch-id>/
```

Directories use mode `0700` and files use mode `0600`.

## Core artifacts

| Artifact | Purpose |
|---|---|
| `run.json` | Current state plus the validated transition history |
| `request.json` | Prompt source type/path, SHA-256, byte length, and retention status |
| `events.jsonl` | Versioned lifecycle envelopes for this dispatch |
| `stdout.log` / `stderr.log` | Raw provider streams retained while they are also forwarded live |
| `result.json` | Terminal status, timing, exit/signal, sanitized arguments, output hashes, and artifact paths |
| `prompt.md` | Present only when `--routing-retain-prompt` was explicitly passed |
| `hooks/` | Captured hook stdout, stderr, and status documents |
| `workspace.json` | Isolated-worktree ownership, repository identity, base, branch, and retained path |
| `changeset.json` | Captured commit/path/status/diffstat manifest for an isolated dispatch |
| `changes.patch` / `working.patch` | Binary-safe complete patch and post-commit working patch |

Prompt contents are absent by default, but provider output can contain source or secrets. There is no automatic deletion.

## Inspecting and cleaning runs

```bash
model-routing runs list
model-routing runs show <dispatch-id-or-unique-prefix>
model-routing runs logs <dispatch-id-or-unique-prefix> --channel stdout|stderr|both
model-routing runs diff <dispatch-id-or-unique-prefix>
model-routing runs apply <dispatch-id-or-unique-prefix> --target <repo>
model-routing runs discard <dispatch-id-or-unique-prefix> --yes
model-routing runs cleanup --older-than 30
model-routing runs cleanup --all
```

Cleanup is explicit and skips a run while its owned isolated worktree still exists. A missing or ambiguous UUID prefix returns nonzero rather than choosing a run silently.

## State and ledger relationship

The structured run store is additive. The existing observations ledger remains at `~/.claude/subagent-model-routing/ledger/observations.jsonl` unless `SUBAGENT_MODEL_ROUTING_LEDGER` overrides it. Extended ledger rows include `dispatch_id`, schema version, attempt, and workspace.

Workflow attempts additionally carry `workflowId`, `taskId`, effort, and attempt number in run state/results/events, plus `workflow_id`, `task_id`, and `attempt` in ledger rows. The scheduler assigns the dispatch UUID before launch, so these identifiers remain stable through preflight, retries, cancellation, and resume. Workflow state itself lives under `workflows/<workflow-id>/`; see [host-neutral workflows](workflows.md).

Legacy asymmetries remain deliberate:

- usage and missing-GNU-timeout failures write no ledger row;
- `started` rows omit exit, wall time, and outcome;
- unreadable prompts preserve each shim's existing ordering;
- a clipped process can leave an orphaned `started` row for `distill` to report;
- legacy outcome still treats exit `124` as timeout, while `supervisor_timeout` distinguishes whether the Python supervisor actually fired.

Application is not a lifecycle state. Worktree integration records `applied`, `conflicted`, or `discarded` under `result.json.integration` without transitioning a terminal dispatch.
