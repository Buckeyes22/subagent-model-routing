# Prompt Engineering Reference Collection — Index

A set of five standalone, first-party-grounded prompt-engineering reference documents, one per model family. Each is self-contained; this index records what they are, how they were built, and the cross-cutting caveats that apply to all of them.

| Model family | Document |
|---|---|
| OpenAI (Codex / GPT) | `prompting/openai-codex-gpt-prompting-reference.md` |
| GLM (Zhipu AI / Z.ai) | `prompting/glm-zhipu-prompting-reference.md` |
| Kimi (Moonshot AI) | `prompting/kimi-moonshot-prompting-reference.md` |
| Qwen (Alibaba) | `prompting/qwen-alibaba-prompting-reference.md` |
| MiniMax | `prompting/minimax-prompting-reference.md` |

---

## Methodology

"Official" was scoped to **first-party content only**: vendor developer docs and API platforms, the vendor's own GitHub org, and HuggingFace model cards published by the vendor's org account. Third-party blogs, aggregators, and community guides were excluded except where they pointed to a first-party source, in which case the first-party source was used. Where a document includes a non-first-party claim (e.g., a widely-reported model behavior not in the vendor's docs, or an external reference recommendation), it is **explicitly flagged as non-official** in that document.

For the two vendors whose English/international docs were ambiguous (Z.ai and MiniMax), the documentation **indexes were pulled directly** rather than inferring coverage from search results, to confirm whether a dedicated prompting page actually exists. Content was extracted from the live official pages where the docs were machine-readable; OpenAI's developer docs are JavaScript-rendered and were reconstructed from official prose extracts plus the live doc-structure map.

Compiled June 2026. Every document carries its own source list; prefer those links over this summary.

---

## Coverage at a glance

The single most useful cross-vendor finding: **a dedicated text-prompting guide is not a given.** Three of the five publish one for their text models; one publishes one only on its Chinese platform; one publishes none for text at all.

| Vendor | Dedicated text-prompt guide? | Where | Language | Notes |
|---|---|---|---|---|
| OpenAI | Yes, extensive (multiple tracks) | `developers.openai.com` | English | The reference standard; separate GPT and Codex tracks; version-specific guidance |
| Qwen | Yes, example-heavy | Alibaba Cloud Model Studio | English (+ Chinese) | Built around a named 6-element framework |
| Kimi | Yes | `platform.moonshot.ai` / `platform.kimi.ai` | English | Mirrors OpenAI's taxonomy; strong agent/tool-specific notes |
| GLM | Yes, but **Chinese platform only** | `docs.bigmodel.cn` | Chinese | International `docs.z.ai` has **no** standalone prompt page |
| MiniMax | **No** (text); guides exist for speech + image/video | model cards + API docs | — | Text prompting must be assembled from cards; Anthropic-API-compatible |

---

## Cross-cutting caveats (apply to all five)

**Domain churn from rebrands is a live maintenance hazard.** Zhipu now presents internationally as **Z.ai** (`z.ai` / `docs.z.ai`) while retaining `bigmodel.cn` domestically; Moonshot's platform answers at both `moonshot.ai` and `kimi.ai` with `kimi.com` for China; MiniMax moved its English platform from `minimaxi.com` to `minimax.io` (the old domain is now the China site). Several `minimaxi.com` English paths now 404. If these references are loaded into a knowledge base or RAG pipeline, store the **`llms.txt` index URL** for each vendor that publishes one (OpenAI, Z.ai, and MiniMax all do) rather than deep page links — the indexes survive page reshuffling better.

**For the three Chinese labs, model cards beat prose guides for model-specific tuning.** The richest model-specific knobs — thinking-mode activation and syntax, preserved-thinking replay requirements, sampling defaults — live in the **capability/API pages and HuggingFace model cards**, not the prose prompt guides, which tend to restate standard technique. GLM's thinking-parameter behavior, Kimi's per-family temperatures, MiniMax's `temperature=1.0 / top_p=0.95 / top_k=40`, and Qwen3's `/think` and `/no_think` switches are all card/capability-doc facts, not prompt-guide facts.

**Official vs community must stay separated.** Each document keeps vendor-documented guidance distinct from field heuristics. The clearest example is GLM's widely-reported positional bias toward the start of the prompt — a useful heuristic, but **not** in Zhipu's official docs, and labeled accordingly.

**Versioning moves fast.** All five families shipped multiple releases inside a few months (e.g., MiniMax M2 → M2.1 → M2.5 → M2.7 → M3; GLM 4.x → 5.x; Kimi K2 → K2.7). Parameter recommendations and thinking-mode behavior are version-specific; re-check the model card on each upgrade.

---

## Common patterns shared across all five guides

Despite different framings, the official guides converge on the same core taxonomy, which is worth internalizing once and applying everywhere:

- **Clear, specific instructions** as the highest-leverage move (stated as "the most important step" by both Qwen and GLM).
- **Role/persona assignment** via the system message.
- **Delimiters** to separate instruction from content — triple quotes (GLM, Kimi), XML tags (Kimi), or high-recognizability separators like `###` / `===` / `>>>` (Qwen).
- **Few-shot / output examples** for hard-to-describe styles and output consistency.
- **Explicit task-step decomposition** for complex or multi-step tasks.
- **Reference text / grounding** with an explicit "say so if the answer isn't present" instruction to suppress hallucination.
- **Recursive chunk-and-summarize** for documents exceeding the context window.
- **The output-length caveat** — every guide that addresses length notes the model hits structural targets (paragraphs, bullets) more reliably than exact word counts.

Where the families genuinely diverge is in **reasoning/thinking control** (each has its own parameter and activation semantics), **tool-use prompting philosophy** (notably Kimi's instruction *not* to describe tools in the system prompt, versus OpenAI's structured tool examples), and **agentic-coding scaffolding** (OpenAI's `AGENTS.md` and four prompt elements; MiniMax's architect-style spec-writing tendency). Those divergences are where the per-family documents earn their keep.

---

## Synchronization Matrix

These reference files are the canonical source for model-specific prompting guidance. The runtime skills intentionally duplicate compact operational cards, so future guidance changes must update every surface listed here in the same change. Capability tiers are maintained in the plugin ledger (`plugins/subagent-model-routing-claude/skills/subagent-model-routing/ledger/`); prompting guidance here is tier-independent.

| Model family | Canonical reference | Route status | Runtime cards | Human/audit surfaces |
|---|---|---|---|---|
| OpenAI / Codex / GPT | `prompting/openai-codex-gpt-prompting-reference.md` | Active via `codex-shim` | `plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-codex/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-copilot/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards` | `README.md`; `plugins/subagent-model-routing-claude/README.md`; `plugins/subagent-model-routing-codex/README.md`; `plugins/subagent-model-routing-copilot/README.md` |
| Kimi / Moonshot | `prompting/kimi-moonshot-prompting-reference.md` | Active via `opencode-shim kimi-for-coding/k2p7` | `plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-codex/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-copilot/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards` | `README.md`; `plugins/subagent-model-routing-claude/README.md`; `plugins/subagent-model-routing-codex/README.md`; `plugins/subagent-model-routing-copilot/README.md` |
| GLM / Z.ai | `prompting/glm-zhipu-prompting-reference.md` | Active via `opencode-shim zai-coding-plan/glm-5.2` | `plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-codex/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-copilot/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards` | `README.md`; `plugins/subagent-model-routing-claude/README.md`; `plugins/subagent-model-routing-codex/README.md`; `plugins/subagent-model-routing-copilot/README.md` |
| MiniMax | `prompting/minimax-prompting-reference.md` | Active via `opencode-shim minimax/MiniMax-M3` | `plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-codex/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-copilot/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards` | `README.md`; `plugins/subagent-model-routing-claude/README.md`; `plugins/subagent-model-routing-codex/README.md`; `plugins/subagent-model-routing-copilot/README.md` |
| Qwen / Alibaba | `prompting/qwen-alibaba-prompting-reference.md` | Active via opencode custom provider (any OpenAI-compatible endpoint) | `plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-codex/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards`; `plugins/subagent-model-routing-copilot/skills/subagent-model-routing/SKILL.md` -> `Prompt Reference Cards` | `README.md`; `plugins/subagent-model-routing-claude/README.md`; `plugins/subagent-model-routing-codex/README.md`; `plugins/subagent-model-routing-copilot/README.md` |

## Update Checklist

When any canonical prompt reference changes:

1. Update the corresponding runtime card in `plugins/subagent-model-routing-claude/skills/subagent-model-routing/SKILL.md`.
2. Update the corresponding runtime card in `plugins/subagent-model-routing-codex/skills/subagent-model-routing/SKILL.md`.
3. Update the corresponding runtime card in `plugins/subagent-model-routing-copilot/skills/subagent-model-routing/SKILL.md`.
4. If route status changed, update this matrix and the allowed-routes text in the runtime skills.
5. If the change affects user-facing orientation, update `README.md`, `plugins/subagent-model-routing-claude/README.md`, `plugins/subagent-model-routing-codex/README.md`, or `plugins/subagent-model-routing-copilot/README.md`.
6. Run the structural prompt-reference validation checks.

Qwen is active through opencode as a custom provider pointed at any OpenAI-compatible endpoint. If that route changes, update this matrix, the runtime cards, allowed-routes text, README surfaces, in the same change.
