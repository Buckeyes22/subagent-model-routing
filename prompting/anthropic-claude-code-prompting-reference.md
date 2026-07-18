# Anthropic Claude Code prompting and transport reference

This is the canonical transport reference for prompts sent through `claude-shim.sh`. It is grounded in Anthropic's official Claude Code CLI reference; version-specific model guidance is grounded in the officially hosted system cards linked below.

## Harness and route

Claude Code's non-interactive mode is `claude -p "query"`. The CLI supports text, JSON, and streaming JSON output; this repository fixes the shim contract to text so the shared `SHIM-DONE exit=<n>` sentinel remains the final machine-checkable line.

The Codex and GitHub Copilot CLI packages route Claude work through:

```bash
~/.claude/scripts/claude-shim.sh <prompt-file> [claude flags]
```

The shim reads the prompt file (or stdin via `-`), starts Claude Code in print mode, disables session persistence for the one-shot run, selects the latest `sonnet` alias unless `--model` is supplied, requests text output, and appends the shared JSONL ledger records.

The Claude Code package does not route Claude through this shim. Claude-hosted work should use Claude Code's native `Agent` surface instead of spawning a nested Claude Code session.

## Version-specific model references

- [Claude Sonnet 5](anthropic-claude-sonnet-5-prompting-reference.md) — default routed Claude workhorse; system-card evidence covers coding, agentic search, multimodal reasoning, professional work, reliability, and prompt injection.
- [Claude Opus 4.8](anthropic-claude-opus-4.8-prompting-reference.md) — difficult general engineering, deep analysis, and verification-heavy work.
- [Claude Fable 5](anthropic-claude-fable-5-prompting-reference.md) — hardest generally available work, with explicit safeguard/fallback and authorization-boundary caveats.

This project intentionally does not maintain a Mythos-specific route or model reference.

## Model and effort selection

Claude Code accepts the model aliases `sonnet`, `opus`, `haiku`, and `fable`, plus full model names. This repository defaults routed Claude work to `sonnet`; exact version-specific claims apply only while an alias resolves to the referenced model:

```bash
~/.claude/scripts/claude-shim.sh /tmp/task.md
~/.claude/scripts/claude-shim.sh /tmp/task.md --model opus
~/.claude/scripts/claude-shim.sh /tmp/task.md --model haiku
~/.claude/scripts/claude-shim.sh /tmp/task.md --model sonnet --effort low
```

The CLI supports `low`, `medium`, `high`, `xhigh`, `max`, and `ultracode` effort settings, but availability depends on the selected model. Direct shim calls pass these through and preserve the CLI's exit code. Versioned workflow documents intentionally allow only the registry-declared portable subset (`low`, `medium`, `high`, `xhigh`, `max`) so validation remains deterministic across hosts.

## Prompt shape for routed coding work

Claude Code is an agentic coding harness with file and shell tools. For routed work, this repository recommends prompts with:

1. A concrete objective and the relevant repository context.
2. Explicit file, directory, and authorization boundaries.
3. The work to perform and artifacts to produce.
4. Deterministic validation commands.
5. Completion criteria and the expected final report.

This is project guidance inferred from the agentic CLI workflow, not a required Anthropic template.

Example:

```text
Objective: Fix the parser regression described below.
Context: The implementation is in src/parser.ts and tests are in test/parser.test.ts.
Boundaries: Stay within those files. Do not change public APIs or dependencies.
Work: Inspect the implementation, make the smallest correct fix, and add a regression test.
Validation: Run npm test -- parser.test.ts and npm run typecheck.
Completion: Leave the edits in the workspace and report changed files plus command results.
```

Do not pass `--bare` by default: bare mode skips project CLAUDE.md files, hooks, skills, plugins, MCP servers, and memory. The routed agent should normally discover the same project instructions and tools as an interactive Claude Code session.

## Permissions, limits, and authentication

With `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1`, the shim passes `--dangerously-skip-permissions` because an unattended print-mode run cannot answer approval prompts. Set it to `0` to preserve Claude Code's configured permission policy. Callers can forward an explicit `--permission-mode`, tool allow/deny rules, or other supported policy flags.

For bounded automation, Claude Code also exposes `--max-turns` and `--max-budget-usd`. These are useful per-dispatch safety controls and pass through after the prompt source.

Authenticate interactively with `claude auth login`. `claude auth status` reports authentication state as JSON and exits nonzero when logged out. Subscription-backed CI can generate a long-lived token with `claude setup-token`; handle it as a secret and never record it in prompts or the routing ledger.

## Official source

- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
