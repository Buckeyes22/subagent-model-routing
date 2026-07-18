# Changelog

All notable changes to this project will be documented in this file.

The project adheres to **semantic versioning intent** with the following public contract. The items below are considered the stable public API and will only change in a **MAJOR** release:

- The `SHIM-DONE` sentinel format emitted by the transport shims.
- The shim environment variable names: `SHIM_TIMEOUT_SECS`, `SUBAGENT_MODEL_ROUTING_UNRESTRICTED`, and `SUBAGENT_MODEL_ROUTING_LEDGER`.
- The namespaced agent types used for routing.
- The versioned workflow JSON schema and persisted task-state names.

New capabilities bump the **MINOR** version; fixes bump the **PATCH** version.

## [Unreleased]

## [0.6.0] - 2026-07-17

### Added
- A dedicated `kimi-shim.sh` transport backed by the Kimi Code CLI, including registry, doctor, workflow, installer, host-package, tripwire, and test-suite integration. Kimi now uses its configured CLI default or an explicit `--model` override instead of routing through OpenCode.
- Read-only Kimi configuration validation through `kimi doctor config` and explicit, credential-safe configured-model discovery through bounded `kimi provider list --json` parsing.
- A dependency-free `model-routing setup providers` checkbox installer for missing Codex, Claude Code, Grok Build, Kimi Code, and OpenCode CLIs, including `/dev/tty` bootstrap support, dry-run review, first-party redirect/size validation, partial-failure recovery, and offline PTY/bootstrap tests.

### Changed
- Kimi model attribution now follows the CLI's documented precedence (`-m`/`--model`, `KIMI_MODEL_NAME`, then `default_model`). Prompt-mode-incompatible permission flags and shim-owned prompt/output flags fail as usage errors before provider startup, and the registry now declares that Kimi has no per-invocation effort control.
- Vendor system cards are now cited at their official hosted URLs instead of being redistributed as complete converted copies.
- Public release candidates are assembled from an explicit allowlist and checked for private maintainer data before publication.
- CI actions are immutable SHA references, checkout credentials are not persisted, and development dependencies install from a hash-locked file.
- Provider installer downloads verify maintainer-pinned SHA-256 digests when available and report the resolved source, digest, and installed CLI version.

## [0.5.0] - 2026-07-10

### Added
- Explicit `model-routing doctor --discover-models` checks. OpenCode uses its bounded documented model-list command, Codex reads its CLI-managed local cache, and unsupported discovery surfaces report `SKIP`; failures and output drift remain non-blocking warnings.
- A versioned JSON workflow schema and semantic validator with cycle detection, native-host route checks, alias resolution, safe prompt paths, explicit context selection, retry validation, and argv-only verification commands.
- A persistent foreground workflow scheduler with global/per-provider concurrency, deterministic dependency release, fail-fast/continue policies, bounded context handoff, fresh-worktree retries, post-dispatch verification, Ctrl+C/external cancellation, and resume without rerunning successful tasks.
- `model-routing workflow run|list|show|resume|cancel`, workflow/task/attempt lineage in dispatch records/events/ledger entries, private atomic workflow state, and dependency/failure-resume examples.

### Changed
- Codex and Copilot packages now document executable dependency workflows. Claude continues to prefer native Workflow and retains tripwire enforcement; the runner's self-declared `--host` validation is advisory.
- All three package versions and public documentation now reflect the completed Phase 6 scope.
- Discovery, verification, and lifecycle-hook subprocess output is drained with fixed memory bounds; lifecycle output events are emitted after provider pipe drainage so hook latency cannot deadlock a child.
- Workflow cancellation now uses an active scheduler lease plus locked state merging instead of trusting a persisted PID, resume can verify the persisted host, and Claude's Stop hook blocks shared-runner commands that declare a non-Claude host.
- CI now enforces Ruff, strict mypy, JSON instance/schema validation, plugin structure/native-host boundaries, local Markdown links, clean diffs, and GitHub Actions syntax.

## [0.4.0] - 2026-07-10

### Added
- A versioned, non-destructive `model-routing doctor` with runtime, provider, plugin, and security checks; provider filtering; JSON output; installation-only mode; and explicitly opted-in read-only authentication probes. Default doctor and dispatch preflight perform no live model discovery.
- Opt-in `shared`, `isolated`, and declared-task `auto` workspace modes. Isolated writes run on owned `model-routing/<dispatch-id>` Git worktrees below the private state root and retain binary-safe patches without changing the caller's worktree.
- Explicit `runs diff`, `runs apply`, and `runs discard` integration commands. Application validates repository identity and a path manifest, preserves terminal dispatch state, and records applied/conflicted/discarded integration metadata separately.
- Worktree, doctor, no-network/default-probe, patch application, conflict, ownership, installer-doctor, and cleanup-retention tests.

### Changed
- The installer now runs `model-routing doctor --installation-only`; bootstrap output points users to the full doctor.
- Run cleanup preserves active isolated worktrees until an explicit discard, and run records include workspace/change artifacts when present.
- Discard now requires an exact live Git worktree/branch/owner/path match and refuses raw filesystem fallback deletion, including after metadata tampering or repository moves.

## [0.3.0] - 2026-07-10

### Added
- GPT-5.6 Sol, Terra, and Luna routing guidance for `codex-shim`, including inline `--model=` attribution and focused forwarding tests.
- A `grok-shim` transport for xAI Grok Build, defaulting to Grok 4.5, with routing guidance across the Claude Code, Codex, and GitHub Copilot CLI packages.
- A `claude-shim` transport for Claude Code print mode, defaulting to the `sonnet` alias, as a target route for the Codex and GitHub Copilot CLI packages.
- Officially linked Claude Sonnet 5, Opus 4.8, and combined Fable 5/Mythos 5 system cards, with separate evidence-grounded prompting references and capability cards for Sonnet 5, Opus 4.8, and Fable 5. Mythos intentionally has no route-specific reference or card.
- A Python 3.11+ standard-library runtime shared by all four compatibility shims, with process-group timeout/cancellation, streamed and retained output, private atomic run records, lifecycle events, fail-open portable hooks, and `model-routing runs` inspection/cleanup commands.
- A canonical provider registry, semantic validator, JSON schemas, and generated host-specific route catalogs that enforce Claude/Codex native-provider boundaries.
- The additive `CODEX_BIN` executable override, bringing Codex to parity with the other shim transports.

### Changed
- The Codex-native package no longer routes back through `codex-shim`; Codex work stays native/inline there, while `codex-shim` remains available to Claude Code and Copilot.
- The public Bash shims are now thin wrappers over the shared runtime while retaining the v0.2 sentinel bytes, exit codes, prompt delivery, provider argv, telemetry, and per-shim ledger asymmetries.

## [0.2.0] - 2026-07-08

### Added
- Standalone `codex` and `opencode` transport shims, formalized around the `SHIM-DONE` contract.
- Provider-agnostic routing: supports any opencode provider, including local OpenAI-compatible endpoints.
- Routing skill with flat one-shot dispatch and Workflow DAG orchestration for Claude Code, plus direct-shell packages for Codex and GitHub Copilot CLI.
- Fail-open guardrail hooks for tripwire-style safety checks.
- Clone-optional bootstrap installer (`scripts/bootstrap.sh`, with `scripts/install.sh` for cloned checkouts).
- Opt-in OTLP observability.
- Quantitative dispatch ledger with seed capability cards.
- Continuous integration covering syntax, sentinels, manifests, and hook pipe tests.
