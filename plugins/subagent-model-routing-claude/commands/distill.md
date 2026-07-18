---
description: Distill hot-tier model observations into the committed capability cards and the SKILL.md rankings block.
argument-hint: [optional focus, e.g. "minimax" or "since 2026-07-01"]
---

Distill the subagent-model-routing ledger. Work inline (no dispatch needed):

1. **Resolve the writable source checkout.** First try `git rev-parse --show-toplevel` from the current directory and accept it only if it contains `plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger`. Otherwise try `${SUBAGENT_MODEL_ROUTING_HOME:-$HOME/.local/share/subagent-model-routing}` and accept it only if it is a Git checkout containing that ledger directory. Set `ROOT` to the accepted absolute path, `LEDGER_DIR="$ROOT/plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger"`, and `SKILL="$ROOT/plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md"`. If neither candidate qualifies, stop and tell the user to run the command from the source checkout or set `SUBAGENT_MODEL_ROUTING_HOME` to it. Never edit an installed plugin cache: those edits are neither durable nor necessarily in Git.
2. **Read the hot log.** Use `${SUBAGENT_MODEL_ROUTING_LEDGER:-$HOME/.claude/subagent-model-routing/ledger/observations.jsonl}`. Scope to entries newer than the newest "Last distilled" date across `$LEDGER_DIR/*.md` (or the $ARGUMENTS focus). If no card carries an ISO date yet, treat all entries as in scope. If the file is missing or empty, say so and stop.
3. **Summarize per model.** Report dispatch counts, failure/clip/stall rates, wall-time distribution from `source:"shim"` terminal lines (`event:"finished"`, or legacy lines with no `event`), and every qualitative `note` from `source:"orchestrator"` lines. Treat `source:"shim", event:"started"` as orphan/killed-run visibility only; report starts without matching finished lines separately, but do not count them as completed dispatch outcomes. Quote notes verbatim in the working summary.
4. **Map each record by both `shim` and `model`; do not derive a filename from the model string alone.**
   - `shim:"codex"` with a GPT model ID -> `$LEDGER_DIR/codex.md`.
   - `shim:"grok"` with `grok-*` -> `$LEDGER_DIR/grok.md`.
   - `shim:"claude"`: `sonnet` -> `claude-sonnet-5.md`, `opus` -> `claude-opus-4.8.md`, and `fable` -> `claude-fable-5.md` only while the installed alias resolves to that exact version. Apply the same rule to full Claude model IDs after identifying their version. If an alias has advanced, use an existing matching versioned card or ask before creating one. Never create a Mythos-specific card.
   - `shim:"kimi"` with a Kimi model ID or configured-default label -> `kimi.md`.
   - `shim:"opencode"`: legacy Kimi provider/model strings such as `kimi-*` or `kimi-for-coding/*` -> `kimi.md`; Z.ai/GLM strings such as `zai-*`, `zai-coding-plan/*`, or `glm-*` -> `glm.md`; case-insensitive `minimax*` provider/model strings -> `minimax.md`; Qwen provider/model strings -> `qwen.md`.
   - For an unknown custom provider, update an existing card only when the mapping is explicit and unambiguous. Otherwise report the unmapped records and ask the user which existing card owns them; do not invent a card silently.
5. **Propose card updates.** For each mapped model with new evidence, edit its existing card: move confirmed patterns into Excels/Struggles/Caveats with an evidence pointer (date plus one-line summary), and update "Last distilled". Do not change a Tier line unless the evidence is strong and you flag it prominently.
6. **Update rankings only when warranted.** Rewrite the block between `<!-- LEDGER:RANKINGS START -->` and `<!-- LEDGER:RANKINGS END -->` in `$SKILL` only if tiers or seats changed; otherwise update its "last distilled" date only.
7. **Show the durable diff.** Run `git -C "$ROOT" diff -- "$LEDGER_DIR" "$SKILL"` and give a one-paragraph summary. Do not commit; the user reviews and commits.
8. **Call out material changes.** If a tier moved or a confirmed failure mode was added, remind the user to promote it to the brain through an inbox page and PR per the brain's `CLAUDE.md`.
