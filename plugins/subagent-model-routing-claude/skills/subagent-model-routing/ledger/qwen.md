# Qwen — capability card (seed example)

> Seed example — maintain via `/subagent-model-routing-claude:distill` and your own ledger.

- **Tier:** Local / experimental (unranked — pending benchmark) *(seed ranking)*
- **Excels at:** local/experimental, unranked
- **Struggles with:** (not yet benchmarked against the roster — observations pending)
- **Operational caveats:** routes through opencode as a custom provider — any OpenAI-compatible endpoint, addressed as your `<provider>/<model>` entry; MCP tool availability follows your opencode configuration (for small-context local models, consider skipping heavy tool schemas — context is better spent on prompt and source)
- **Evidence:** seed default — replace with your own observations via `/subagent-model-routing-claude:distill`; observations accumulate in `~/.claude/subagent-model-routing/ledger/observations.jsonl`
- **Last distilled:** 2026-07-07 (seed)
