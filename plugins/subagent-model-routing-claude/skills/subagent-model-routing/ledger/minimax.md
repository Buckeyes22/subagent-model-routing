# MiniMax-M3 — capability card (seed example)

> Seed example — maintain via `/subagent-model-routing-claude:distill` and your own ledger.

- **Tier:** Sonnet peer (Sonnet-grade throughput) *(seed ranking)*
- **Excels at:** sonnet-grade throughput
- **Struggles with:** intermittent stalls — retry ≤3, no reroute
- **Operational caveats:** stall detection/retry machinery retained as cheap insurance; `--thinking` is a binary visibility toggle for M3, not an effort dial; no official text prompt-engineering guide — use Anthropic-style structured prompting
- **Evidence:** seed default — replace with your own observations via `/subagent-model-routing-claude:distill`; observations accumulate in `~/.claude/subagent-model-routing/ledger/observations.jsonl`
- **Last distilled:** 2026-07-07 (seed)
