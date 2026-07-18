# Runtime architecture

This document defines the compatibility and ownership boundaries for the local subagent-model-routing runtime introduced in v0.3.0. It is an implementation contract, not a model-ranking guide; model evidence and prompting guidance remain under `prompting/` and the package-local skill references.

## Product boundary

The project remains a local plugin and command-line transport layer. It does not run a daemon, web UI, SQLite service, tmux control plane, mobile client, or persistent agent-team service. The shared runtime adds bounded process supervision, local run artifacts, non-destructive diagnostics, opt-in worktrees, and a foreground JSON dependency scheduler to the existing one-shot shims.

The five public shell entrypoints are:

- `scripts/codex-shim.sh`
- `scripts/claude-shim.sh`
- `scripts/grok-shim.sh`
- `scripts/kimi-shim.sh`
- `scripts/opencode-shim.sh`

Their prompt-source syntax, forwarded provider arguments, exit status, ledger behavior, and final `SHIM-DONE exit=<n>` line are public compatibility surfaces. `tests/test_shim_contract.py` characterizes the v0.2 behavior before the runtime rewrite.

## Client ownership

Client-native routing boundaries are intentional:

- Claude Code keeps Claude work in native Agent or Workflow calls and exposes Codex, Kimi, Grok, and OpenCode transports.
- Codex keeps GPT/Codex work in the native Codex harness and exposes Claude, Kimi, Grok, and OpenCode transports.
- GitHub Copilot may invoke all five transports.

Generated route assets may share a canonical registry, but client-specific prose, commands, agents, hooks, and manifests must remain separate. Claude-only Workflow and Stop-hook instructions must never leak into the Codex or Copilot packages.

## Layer responsibilities

```text
host plugin or direct shell
          │
          ▼
public Bash shim compatibility wrapper
          │
          ▼
Python 3.11+ model-routing runtime
  ├── provider registry and adapter
  ├── prompt/provider preflight
  ├── child process supervision
  ├── legacy ledger append
  ├── structured run artifacts
  └── fail-open lifecycle events/hooks
```

The Bash wrappers own only Python discovery, provider selection, and the legacy usage-error fallback when Python itself is unavailable. Provider adapters own binary resolution, model parsing, provider argv, prompt delivery, permission flags, and provider-specific telemetry. The shared runtime owns timeout/cancellation, streaming, the sentinel, run state, artifact permissions, ledger writes, and lifecycle hooks.

Provider commands are always executed as argument arrays without `shell=True`.

## Dispatch lifecycle

Core dispatch states are:

```text
created → preflighting → ready → running → succeeded
                      ↘ preflight_failed
                                  running → failed | timed_out | cancelled
```

Terminal states never transition back to `running`. Later worktree application is integration metadata, not a dispatch state.

Each accepted dispatch receives a UUID used by its run directory, lifecycle events, and extended ledger fields. Compatibility failures that occur before a run begins retain the v0.2 ledger asymmetries pinned by the golden tests.

## Local state

Run artifacts live below `${XDG_STATE_HOME:-$HOME/.local/state}/subagent-model-routing/runs/<dispatch-id>/`. Directories use mode `0700`; files use mode `0600`. Prompt bodies are not retained unless explicitly requested. Provider stdout and stderr are retained for recovery and inspection and may contain source or secrets.

The existing observations ledger path and record fields remain supported. Extended fields are additive, and `distill` continues treating unmatched `started` records as interrupted-run visibility rather than completed outcomes.

The Python supervisor owns the actual timeout and process-group termination. GNU `timeout`/`gtimeout` remains a checked compatibility prerequisite in v0.3 so the established exit-127 and no-ledger behavior does not change during the rewrite.

## Prompt exposure

Codex and OpenCode receive prompts on stdin. Claude Code, Kimi Code, and Grok Build pass prompt bodies in argv, which can expose them to same-user process inspection while the provider runs. On-disk retention controls do not mitigate argv visibility. Changing those providers to stdin requires separately verified CLI support.

## Hooks and failure policy

Runtime lifecycle hooks receive versioned JSON on stdin, execute without a shell, have independent timeouts, and fail open by default. Hook output is captured to run artifacts and must never be appended after the public sentinel. Claude Stop hooks remain host-specific guardrails and are not replaced by runtime lifecycle hooks.

## Worktrees, discovery, and workflows

v0.4.0 adds opt-in isolated worktrees and the local doctor on top of the v0.3 run store. v0.5.0 completes Phase 6 with explicit discovery plus a foreground, host-neutral dependency scheduler. Workflow state is atomically persisted under the same private state root; every attempt is still an ordinary dispatch with workflow/task/attempt lineage. The runner adds no daemon or database. Claude's native Workflow remains authoritative for Claude-hosted DAGs, and self-declared `--host` validation is advisory while Claude tripwire hooks remain the enforcement layer.

## Clean-room constraint

Devchain informed the capability analysis, but this implementation is independently designed for this repository and must not copy Elastic License 2.0 source code.
