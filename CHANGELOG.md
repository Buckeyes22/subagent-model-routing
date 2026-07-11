# Changelog

All notable changes to this project will be documented in this file.

The project adheres to **semantic versioning intent** with the following public contract. The items below are considered the stable public API and will only change in a **MAJOR** release:

- The `SHIM-DONE` sentinel format emitted by the transport shims.
- The shim environment variable names: `SHIM_TIMEOUT_SECS`, `SHIM_RESULT`, `SUBAGENT_MODEL_ROUTING_UNRESTRICTED`, and `SUBAGENT_MODEL_ROUTING_LEDGER`.
- The namespaced agent types used for routing.

New capabilities bump the **MINOR** version; fixes bump the **PATCH** version.

## [Unreleased]

### Added
- Optional `SHIM_RESULT=1` transport receipts, emitted as the exact finished ledger record immediately before the final `SHIM-DONE` sentinel.
- `scripts/parse-shim-result.py`, a reference parser that ignores spoofed child output and validates the trailing receipt/sentinel exit codes.
- Per-dispatch IDs and active execution-policy profiles in routing-ledger records.

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
