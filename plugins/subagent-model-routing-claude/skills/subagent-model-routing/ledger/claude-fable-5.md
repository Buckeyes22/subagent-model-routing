# Claude Fable 5 — capability card (seed example)

> System-card prior — maintain routing confidence via `/subagent-model-routing-claude:distill` and your own ledger.

- **Route:** `claude-shim.sh <prompt-file> --model fable` from the Codex and Copilot packages; Claude-hosted work uses native `Agent` calls
- **Tier:** hardest generally available Claude seat; unranked against other providers until local ledger evidence exists
- **Excels at:** frontier-level general coding, long-context agentic work, multimodal and professional tasks; published safeguarded results exceed Opus 4.8 on several coding benchmarks
- **Struggles with:** high-risk biology and cybersecurity requests can be blocked or silently fall back to Opus 4.8; external testing found occasional rationalization of questionable multi-agent behavior
- **Operational caveats:** production safeguards are part of the route, so benchmark and local behavior may combine the underlying Fable path with fallback. Use narrow authorization boundaries, confirmation gates for destructive/external actions, and deterministic verification. This repository intentionally has no Mythos route/card.
- **Evidence:** official [Claude Fable 5 & Claude Mythos 5 System Card](https://www.anthropic.com/claude-fable-5-mythos-5-system-card) (June 9, 2026) via the Fable-only runtime guidance in `../references/model-prompting.md#claude-fable-5`
- **Last distilled:** 2026-07-10 (system-card seed)
