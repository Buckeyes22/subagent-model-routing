---
description: Distill hot-tier model observations into the committed capability cards and the SKILL.md rankings block.
argument-hint: [optional focus, e.g. "minimax" or "since 2026-07-01"]
---

Distill the subagent-model-routing ledger. Work inline (no dispatch needed):

1. **Read the hot log**: `~/.claude/subagent-model-routing/ledger/observations.jsonl`. Scope to entries newer than the newest "Last distilled" date across `plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger/*.md` (or the $ARGUMENTS focus). If no card carries an ISO date yet (fresh install), treat ALL ledger entries as in scope. If the file is missing/empty, say so and stop.
2. **Summarize per model**: dispatch counts, failure/clip/stall rates, wall-time distribution (from `source:"shim"` terminal lines: `event:"finished"` or legacy lines with no `event`), and every qualitative `note` (from `source:"orchestrator"` lines). Treat `source:"shim", event:"started"` as orphan/killed-run visibility only; report starts without matching finished lines separately, but do not count them as completed dispatch outcomes. Quote notes verbatim in your working summary.
3. **Propose card updates**: for each model with new evidence, edit its `ledger/<model>.md` — move confirmed patterns into Excels/Struggles/Caveats with an evidence pointer (date + one-line summary); update "Last distilled". Do NOT change a model's Tier line unless the evidence is strong AND you flag it prominently.
4. **Rewrite the rankings block** between `<!-- LEDGER:RANKINGS START -->` and `<!-- LEDGER:RANKINGS END -->` in SKILL.md ONLY if tiers or seats changed; otherwise update its "last distilled" date only.
5. **Show the user the full diff** (`git diff` of ledger/ + SKILL.md) and a one-paragraph summary. Do not commit — the user reviews and commits.
6. **Material change?** (tier moved, new confirmed failure mode): remind the user to promote it to the brain via an inbox page + PR per the brain's CLAUDE.md.
