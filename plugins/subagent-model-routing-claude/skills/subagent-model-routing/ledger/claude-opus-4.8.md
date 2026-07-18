# Claude Opus 4.8 — capability card (seed example)

> System-card prior — maintain routing confidence via `/subagent-model-routing-claude:distill` and your own ledger.

- **Route:** `claude-shim.sh <prompt-file> --model opus` from the Codex and Copilot packages; Claude-hosted work uses native `Agent` calls
- **Tier:** verification-heavy and difficult-work Claude seat; unranked against other providers until local ledger evidence exists
- **Excels at:** software engineering, agentic tool use, knowledge work, deep repository tracing, long context, professional tasks, and honest code-status summaries
- **Struggles with:** system-card case studies still include fabrication, ignored corrections, skipped cheap verification, and instruction-following failures; unsafeguarded prompt-injection robustness regressed in some agentic settings; refusals can be over-elaborate
- **Operational caveats:** published benchmarks generally used adaptive thinking at maximum effort. The `opus` alias can advance to a newer version; confirm it still maps to Opus 4.8 before applying version-specific claims. Require actual command evidence and explicit untrusted-content boundaries.
- **Evidence:** official [Claude Opus 4.8 System Card](https://www.anthropic.com/claude-opus-4-8-system-card) (May 28, 2026; corrections through June 17, 2026) via `../references/model-prompting.md#claude-opus-48`
- **Last distilled:** 2026-07-10 (system-card seed)
