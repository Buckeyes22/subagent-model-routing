# Changelog

All notable changes to this project will be documented in this file.

The project adheres to **semantic versioning intent** with the following public contract. The items below are considered the stable public API and will only change in a **MAJOR** release:

- The `SHIM-DONE` sentinel format emitted by the transport shims.
- The shim environment variable names: `SHIM_TIMEOUT_SECS`, `SUBAGENT_MODEL_ROUTING_UNRESTRICTED`, and `SUBAGENT_MODEL_ROUTING_LEDGER`.
- The namespaced agent types used for routing.

New capabilities bump the **MINOR** version; fixes bump the **PATCH** version.

## [Unreleased]

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
