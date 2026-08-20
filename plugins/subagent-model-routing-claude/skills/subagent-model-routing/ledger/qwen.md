# Qwen — capability card (seed example)

> Seed example — maintain via `/subagent-model-routing-claude:distill` and your own ledger.

- **Tier:** Local / experimental (unranked — pending benchmark) *(seed ranking)*
- **Excels at:** local/experimental, unranked
- **Struggles with:** (not yet benchmarked against the roster — observations pending)
- **Operational caveats:** dispatches through the Qwen Code CLI via `qwen-shim.sh`; point it at any OpenAI-compatible endpoint (local llama.cpp/llama-swap included) with `~/.qwen/.env` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `QWEN_MODEL` — Qwen Code ≥0.21.14 selects OpenAI-compatible auth when all three are set). The shim never injects `-m`; Qwen Code's own config decides the model unless you pass `--model`. For small-context local models, consider skipping heavy tool schemas — context is better spent on prompt and source
- **Evidence:** seed default — replace with your own observations via `/subagent-model-routing-claude:distill`; observations accumulate in `~/.claude/subagent-model-routing/ledger/observations.jsonl`
- **Last distilled:** 2026-08-19 (seed)
