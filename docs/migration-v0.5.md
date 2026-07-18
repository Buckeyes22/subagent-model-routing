# v0.5 discovery and workflow migration

v0.5 completes the approved implementation plan by adding explicit model discovery and the host-neutral workflow scheduler. It is additive: existing shim invocations, sentinels, environment variables, ledger records, direct run directories, doctor defaults, and isolated-worktree operations remain compatible with v0.4.

New surfaces:

- `model-routing doctor --discover-models`, which invokes only explicitly documented discovery backends and treats unavailable or changed provider output as warnings.
- `model-routing workflow run|list|show|resume|cancel`.
- Workflow/task/attempt lineage in dispatch results, events, and ledger records.
- Private workflow state under the existing XDG-compatible state root.

Default doctor and dispatch preflight still perform no model discovery. Workflow concurrency defaults to two, retries default to one total attempt, write tasks require `auto` or `isolated`, patches are never applied automatically, and retained worktrees are never removed automatically.

Claude users should continue using native Workflow for Claude-hosted graphs. The new runner does not weaken or replace Claude's tripwire hooks; `--host` is advisory validation only.

Pass the original host again when resuming, for example `model-routing workflow resume <workflow-id> --host copilot`. The runner rejects a declared host that differs from persisted workflow state, and Claude's Stop hook blocks observed shared-runner commands that omit `--host claude` or declare another host.
