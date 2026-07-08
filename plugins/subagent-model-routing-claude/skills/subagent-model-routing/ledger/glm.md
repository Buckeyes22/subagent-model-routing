# GLM-5.2 — capability card (seed example)

> Seed example — maintain via `/subagent-model-routing-claude:distill` and your own ledger.

- **Tier:** Opus peer (default routed author) *(seed ranking)*
- **Excels at:** everyday code authoring and review at Opus-peer quality; JSON/structured extraction; balanced throughput
- **Struggles with:** (none confirmed at this tier yet — observations pending)
- **Operational caveats:** coding-plan endpoint via opencode; ~2-5 req/min sustained on medium prompts; code `1302` = ZhipuAI 429
- **Evidence:** seed default — replace with your own observations via `/subagent-model-routing-claude:distill`; observations accumulate in `~/.claude/subagent-model-routing/ledger/observations.jsonl`
- **Last distilled:** 2026-07-07 (seed)
