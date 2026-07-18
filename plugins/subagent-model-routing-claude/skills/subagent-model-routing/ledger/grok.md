# Grok 4.5 — capability card (seed example)

> Seed example — maintain via `/subagent-model-routing-claude:distill` and your own ledger.

- **Route:** `subagent-model-routing-claude:grok-shim` / `grok-shim.sh <prompt-file>`; available from Claude Code, Codex, and Copilot
- **Tier:** provisional and unranked until local ledger evidence justifies a cross-provider seat
- **Excels at:** agentic coding, tool-using software work, repository inspection, and knowledge tasks through the Grok Build harness
- **Struggles with:** no route-specific local failure pattern is established yet; do not infer reliability or rank from first-party capability claims alone
- **Operational caveats:** `grok-4.5` is the shim default; `--effort low|medium|high` controls reasoning depth and xAI documents `high` as the default. The prompt is delivered on argv, unrestricted mode adds `--always-approve`, and Grok Build's sandbox policy remains separate—use explicit boundaries and deterministic checks.
- **Evidence:** first-party Grok 4.5, Grok Build CLI, headless-operation, and enterprise-security documentation under `docs.x.ai`, summarized in `../references/model-prompting.md#xai-grok-45-through-grok-build`; replace routing opinions with local observations in `~/.claude/subagent-model-routing/ledger/observations.jsonl`
- **Last distilled:** 2026-07-10 (first-party documentation seed)
