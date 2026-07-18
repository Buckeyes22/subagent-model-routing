# Claude Sonnet 5 — capability card (seed example)

> System-card prior — maintain routing confidence via `/subagent-model-routing-claude:distill` and your own ledger.

- **Route:** `claude-shim.sh <prompt-file>` or `--model sonnet` from the Codex and Copilot packages; Claude-hosted work uses native `Agent` calls
- **Tier:** default Claude workhorse; unranked against other providers until local ledger evidence exists
- **Excels at:** multi-file coding, terminal work, agentic search, multimodal reasoning, and professional tasks; clear gains over Sonnet 4.6
- **Struggles with:** slightly weaker flawed-result handling than Opus 4.8; higher closed-book abstention/error rates than stronger contemporary Claude models; occasional over-refusal or overly discouraging responses
- **Operational caveats:** published benchmarks generally used adaptive thinking at maximum effort. The `sonnet` alias can advance to a newer version; confirm it still maps to Sonnet 5 before applying version-specific claims. Require source/tool inspection and deterministic checks.
- **Evidence:** official [Claude Sonnet 5 System Card](https://www.anthropic.com/claude-sonnet-5-system-card) (June 30, 2026) via `../references/model-prompting.md#claude-sonnet-5`
- **Last distilled:** 2026-07-10 (system-card seed)
