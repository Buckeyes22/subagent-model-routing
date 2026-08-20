# Kimi K3 — capability card (seed example)

> Seed example — maintain via `/subagent-model-routing-claude:distill` and your own ledger.

- **Tier:** Mid-tier (between GLM-5.3 Opus peer and MiniMax-M3 Sonnet peer) *(seed ranking)*
- **Excels at:** mid-tier authoring, burst parallelism
- **Struggles with:** 1-3 sustained concurrency (502s)
- **Operational caveats:** K3 (`kimi-code/k3`): 2.8T MoE/104B active, 1M context; thinking always on, steer with `reasoning_effort` (`low`/`high`/`max`, default `max`); preserved thinking must be passed back in multi-turn flows; subscription-friendly; concurrency-friendly for parallel candidate fan-out; do not sustain >3 concurrent shim calls (502 pressure); see `../references/model-prompting.md#kimi`
- **Evidence:** seed default — replace with your own observations via `/subagent-model-routing-claude:distill`; observations accumulate in `~/.claude/subagent-model-routing/ledger/observations.jsonl`
- **Last distilled:** 2026-07-07 (seed)
