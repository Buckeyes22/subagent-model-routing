# codex GPT-5.6 family — capability card (seed example)

> Seed example — maintain via `/subagent-model-routing-claude:distill` and your own ledger.

- **Tier:** Sol provisionally holds the strongest-implementer seat (≥ GLM-5.2 Opus peer; reserved for hardest/critical + deepest review); Terra and Luna remain unranked pending local evidence *(seed ranking)*
- **Excels at:** hardest implementation, autonomous verify, deepest review
- **Struggles with:** system-card evaluations found a greater tendency than GPT-5.5 to go beyond user intent; prompts must state authorization boundaries and destructive-action constraints explicitly
- **Operational caveats:** Sol is the flagship route; Terra is the lower-cost route; Luna is the fastest and most cost-efficient route. Treat completion claims as unverified until artifacts and deterministic checks pass, especially after tool failures. Deep multi-file work routinely approaches the 20-min ceiling (split long jobs or raise SHIM_TIMEOUT_SECS deliberately).
- **Evidence:** GPT-5.6 System Card (`https://deploymentsafety.openai.com/gpt-5-6`) plus seed defaults — replace routing opinions with your own observations via `/subagent-model-routing-claude:distill`; observations accumulate in `~/.claude/subagent-model-routing/ledger/observations.jsonl`
- **Last distilled:** 2026-07-09 (seed)
