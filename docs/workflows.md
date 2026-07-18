# Host-neutral dependency workflows

`model-routing workflow` executes versioned JSON dependency graphs over the same five transport shims used by direct dispatch. It is a local, foreground scheduler: there is no daemon, database, UI, or background control plane.

Use the runner when Codex or Copilot needs durable dependency ordering, bounded concurrency, retries, verification, cancellation, or resume. In Claude Code, native Workflow remains the default for Claude-hosted graphs. The host-neutral runner is appropriate there only for an explicitly requested external-only graph.

## Commands

```bash
model-routing workflow run workflow.json --host copilot
model-routing workflow list
model-routing workflow list --json
model-routing workflow show <workflow-id>
model-routing workflow cancel <workflow-id>
model-routing workflow resume <workflow-id> --host copilot
```

Run and resume are foreground operations. `cancel` may be called from another terminal; it records the cancellation request and signals the active scheduler, which in turn interrupts every active shim supervisor. On Ctrl+C the runner prints and persists the workflow ID and resume command.

## Minimal document

```json
{
  "schemaVersion": 1,
  "name": "external-review",
  "defaults": {
    "maxConcurrency": 2,
    "providerConcurrency": {"opencode": 1},
    "timeoutSeconds": 1140,
    "workspace": "auto",
    "failurePolicy": "fail-fast"
  },
  "tasks": {
    "analyze": {
      "route": {"provider": "opencode", "model": "replace-with/provider-model"},
      "mode": "read",
      "prompt": {"file": "prompts/analyze.md"}
    },
    "review": {
      "route": {"provider": "grok", "model": "grok-4.5", "effort": "high"},
      "mode": "read",
      "dependsOn": ["analyze"],
      "contextFrom": [{"task": "analyze", "artifact": "stdout", "maxBytes": 50000}],
      "prompt": {"text": "Review the supplied analysis and identify concrete gaps."}
    }
  }
}
```

Prompt files are resolved relative to the workflow JSON. Absolute paths, parent traversal, symlink escapes, missing dependencies, cycles, native-host routes, unknown providers, unsupported effort values, shell-string verification commands, and write tasks using a shared workspace are rejected before any provider starts. Unknown model identifiers remain warnings only for providers whose registry contract permits pass-through.

## Host-native boundaries

The declared host prevents accidental routing of that host's own family:

- `--host claude` rejects Claude transport tasks. Claude work remains native.
- `--host codex` rejects Codex transport tasks. Codex work remains inline.
- `--host copilot` permits Codex, Claude, Kimi, Grok, and OpenCode tasks.

`--host` is advisory metadata, not an authentication or security boundary. A caller can falsely declare Copilot. Pass it again on resume so the CLI verifies that it matches the persisted workflow host. Claude's tripwire hooks inspect observed shell commands and block `workflow run` or `workflow resume` when a Claude session declares another host; they remain the enforcement layer for native Workflow and delegation behavior.

## Scheduling and failure

Independent roots run concurrently up to `maxConcurrency`; `providerConcurrency` can impose a lower provider-specific limit. A dependent task starts only after every dependency is `succeeded` or `verified`.

With `fail-fast`, the first failure stops new work, already-running tasks finish or cancel, directly affected dependents become `blocked`, and other unstarted tasks become `skipped`. With `continue`, unrelated branches continue while failed dependencies still block their descendants.

Every state transition is atomically persisted below the private state directory:

```text
${XDG_STATE_HOME:-~/.local/state}/subagent-model-routing/workflows/<workflow-id>/
```

Each attempt has a unique dispatch ID and normal run directory. Workflow, task, and attempt lineage is present in run records, lifecycle events, and ledger entries.

## Context handoff

Context is opt-in through `contextFrom`; dependency transcripts are never injected automatically. Supported artifacts are `stdout`, `stderr`, `result`, `patch`, and `diffstat`. The composite prompt identifies the dependency task, provider/model, state, artifact, original byte count, and whether the selected content was truncated.

## Retry and verification

```json
{
  "retry": {
    "maxAttempts": 2,
    "backoffSeconds": 5,
    "on": ["timeout", "transport-error"]
  },
  "verify": [
    ["python3", "-m", "unittest", "discover", "-s", "tests"],
    ["git", "diff", "--check"]
  ]
}
```

One attempt is the default, so retries are disabled unless configured. Usage/configuration errors are never retried. A write retry receives a fresh dispatch ID and isolated worktree. Verification commands are argument arrays executed directly without a shell inside the task workspace. Provider success with passing checks becomes `verified`; a failed check becomes `verification_failed`.

## Resume guarantees

Resume verifies the workflow digest, canonical registry digest, Git common-directory identity, successful task results, retained write worktrees, and absence of a live scheduler. Completed `succeeded` and `verified` tasks never rerun. Incomplete tasks receive new attempts while their earlier attempt history remains intact.

See [dependency-workflow](../examples/dependency-workflow/) and [failure-and-resume](../examples/failure-and-resume/) for editable examples.
