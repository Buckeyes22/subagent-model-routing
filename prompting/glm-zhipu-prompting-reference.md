# GLM (Zhipu AI / Z.ai) — Prompt Engineering Reference

| Field | Value |
|---|---|
| Vendor | Zhipu AI — international brand **Z.ai**, domestic platform **bigmodel.cn** |
| Models in scope | GLM-5.x text series (GLM-5.2, GLM-5.1, GLM-5, GLM-5-Turbo, GLM-4.7, GLM-4.6, GLM-4.5), GLM-V vision series, CogView image |
| Primary access | Z.ai API / bigmodel.cn API (OpenAI-compatible and Anthropic-compatible), GLM Coding Plan, open weights (MIT / Modified-MIT) |
| Official guidance | A dedicated prompt-engineering guide exists, but **only on the Chinese platform** (`docs.bigmodel.cn`). The international `docs.z.ai` has no standalone prompt page. |
| Compiled | June 2026 |

This is the most important structural fact for GLM: the substantive, vendor-authored prompt-engineering guide lives on the **Chinese** documentation site and is written in Chinese. The international Z.ai docs distribute prompting-relevant guidance across parameter and capability pages instead of consolidating it. This document reconstructs the official Chinese guide in English and cross-references the international capability docs.

---

## 1. Official guidance landscape

The dedicated guide is **"提示词工程" (Prompt Engineering)** at `docs.bigmodel.cn/cn/guide/platform/prompt`. It covers prompting strategies for GLM language models and CogView image models and is the canonical first-party source. There is also a **scenario-examples section** at `docs.bigmodel.cn/cn/best-practice/prompt/` (e.g., `talk-prompt`) with worked, domain-specific prompt patterns.

The **international Z.ai docs** (`docs.z.ai`) do **not** contain a standalone prompt-engineering page — this was verified against the live documentation navigation. On Z.ai, prompting guidance is distributed across the **Core Parameters** page (`docs.z.ai/guides/overview/concept-param`), the capability pages (**Thinking Mode**, **Deep Thinking**, **Structured Output**, **Function Calling**, **Context Caching**), and the **migration** page. The vendor's GitHub org (`zai-org`) hosts model READMEs, a cookbook, and task-specific Skills, though those skew toward multimodal prompt generation rather than general text prompting.

Coverage assessment: a genuine official prompt guide exists, but it is generic (standard technique restated) and Chinese-only. The genuinely GLM-specific behavior — thinking-mode activation, preserved-thinking replay, sampling defaults — is documented in the capability and parameter pages, not the prompt guide. For model-specific tuning, read the capability docs; for general technique, the prompt guide suffices.

---

## 2. Message format and API surface

GLM is driven through role-structured messages and is both **OpenAI-compatible** and **Anthropic-compatible**. The standard endpoint differs from the **GLM Coding Plan** endpoint: coding-plan traffic must target `https://open.bigmodel.cn/api/coding/paas/v4` (or the Z.ai coding endpoint) rather than the general API endpoint. System messages set role and behavior; the official guide places heavy weight on the System Prompt as the primary steering tool.

---

## 3. Inference and control parameters

From the official Core Parameters guidance. The thinking parameter is the GLM-specific control that most affects output behavior.

| Parameter | Recommended / behavior | Notes |
|---|---|---|
| `temperature` | Lower for precision | Do **not** modify `temperature` and `top_p` simultaneously |
| `top_p` | **0.8–0.95** | Good choice for diversity while preserving quality |
| `max_tokens` | **≥ 1024** | GLM-4.6 output up to 128K; GLM-4.5 up to 96K. If the limit is hit, output truncates |
| `stream` | `true` for interactive | Strongly recommended for chatbots and real-time code generation |
| `thinking` | `enabled` (default) | Controls chain-of-thought; see §4 |

Token-to-character ratio for GLM is roughly **1 token ≈ 1.6 Chinese characters** (model-dependent); always read the actual count from the response `usage` field.

---

## 4. Reasoning / thinking control

The `thinking` parameter controls whether the model engages chain-of-thought for deeper reasoning and planning. The documented behavior is version-dependent:

- `enabled` (default): On GLM-5.1, GLM-5, GLM-5-Turbo, GLM-5v-Turbo, GLM-4.7, and GLM-4.5V, thinking is **forced**. On GLM-4.6, GLM-4.6V, and GLM-4.5, the model **automatically decides** whether to think.
- `disabled`: Turns off chain-of-thought for faster responses on simple tasks.

Official guidance: enable thinking when the task requires complex reasoning and planning; disable it for simple tasks to reduce latency.

**Preserved thinking** is a GLM-specific operational constraint. To carry reasoning across turns, the platform requires the **full historical `reasoning_content` to be replayed** in subsequent requests, which increases prompt tokens. This is opt-in precisely because of that token cost. With thinking disabled, send `thinking: { type: "disabled" }` to avoid spending the output budget on `reasoning_content` before visible text.

---

## 5. System prompt guidance

The official guide treats the **System Prompt** as the central steering mechanism — used to set role, language style, task mode, and specific behavioral guidance for particular problems. The recommended pattern is to make the System Prompt concrete and behavior-specifying. The guide's own example for an extraction assistant:

```json
{
  "role": "system",
  "content": "You are skilled at extracting key information from text — precise, data-driven, focused on the key facts. Extract key data and facts from the text the user provides, and present the extracted information in clear JSON format."
}
```

---

## 6. Core prompting techniques (official guide)

The official guide organizes technique into three strategies.

### Strategy 1 — Write clear, specific instructions

The clearer and more specific the instruction, the higher the answer quality. The guide enumerates several techniques under this strategy. **Define a System Prompt** to set role and behavior (above). **Provide specific detail requirements** — add the detail and background that constrain the output (its example asks not just "tell me about Saturn" but specifies size, composition, ring system, and unique astronomical phenomena). **Role-play** — instruct GLM to adopt a role (e.g., "As a quantum physicist, explain…") to more accurately mimic that role's behavior and register. **Use delimiters** — mark distinct input sections with triple quotes so the model separates instruction from content:

```
Based on the following content:
""" article content to summarize """
extract the core points and outline.
```

**Chain-of-thought prompting** — require the model to solve step by step and show each reasoning step, which reduces inaccuracy and makes the response easier to evaluate (the guide's example has the model independently solve a math problem, then compare against the user's answer and give feedback, showing each step). **Few-shot learning** — provide examples to steer style and register, then ask for new output in that style. **Specify output length** — request a target length, with the documented caveat that exact word counts are hard to hit; the model is better at hitting a target number of paragraphs or bullet points than an exact word count.

### Strategy 2 — Provide reference material

Citing external material measurably improves answer accuracy, reduces hallucination and fabricated information, and ensures timeliness. This is especially suited to document-based QA. When context length prevents quoting an over-long source directly, use a **Retrieval tool** to fetch semantic slices of the document. The guide's pattern instructs the model to answer using provided search results enclosed in delimiters.

### Strategy 3 — Break complex tasks into simple subtasks

Complex tasks carry higher error rates; the best practice is to restructure them into a sequence of simple, coherent subtasks where each subtask's output feeds the next, forming an efficient workflow. Specific techniques: **Intent understanding and entity extraction** — when output must feed a backend interface, force a fixed output format (JSON) so the interface can parse it without errors (e.g., "when you understand the user's intent to book a meeting room, extract the relevant entities and output as JSON"). **Summarize key prior context** — in long dialogues, periodically refine and summarize earlier exchanges to keep focus, reduce repetition, and speed processing. **Chunk and recursively summarize long documents** — summarize chapter by chapter, then combine and re-summarize into a summary-of-summaries, repeating until the whole document is covered; include necessary earlier-chapter context when later chapters depend on it.

---

## 7. Tool use, structured output, and search

GLM documents **Function Calling** (`docs.z.ai/guides/capabilities/function-calling`), **Structured Output** (`struct-output`), **Tool Streaming Output** (`stream-tool`), and **Context Caching** (`cache`) as capability pages. Native **Web Search** is available as an MCP tool included in paid plans. For backend integrations, the official prompt guidance's recommendation to force a fixed JSON output format (Strategy 3) pairs with the Structured Output capability.

---

## 8. Coding (GLM Coding Plan)

For agentic coding via the GLM Coding Plan, the official quick-start documents a workflow of natural-language requirement analysis → architecture design (let the model design the structure) → implementation, with vision-understanding, web-reading, and open-source-repository MCP servers available to the model. Coding traffic must use the dedicated coding API endpoint, not the general endpoint.

---

## 9. Community-observed characteristics (non-official)

Flagged explicitly as **not** from Zhipu's official documentation, but widely reported by migration guides (e.g., Cerebras): GLM models are commonly described as having a strong **positional bias toward the beginning of the prompt**, meaning the most important instructions are best placed early; and a **thinking mode that activates or is bypassed depending on syntax**, reinforcing the importance of the explicit `thinking` parameter over relying on phrasing. Treat these as field heuristics to validate against your own evals, not vendor guarantees.

---

## 10. Quick reference

| Situation | Action |
|---|---|
| Steering behavior | Use a concrete, behavior-specifying System Prompt |
| Diversity with quality | `top_p` 0.8–0.95; do not also change `temperature` |
| Complex reasoning | `thinking: enabled`; forced on GLM-5.x/4.7/4.5V |
| Simple/fast task | `thinking: disabled` |
| Carry reasoning across turns | Replay full `reasoning_content` (costs tokens) |
| Backend-consumable output | Force fixed JSON format + Structured Output capability |
| Separate instruction from content | Triple-quote delimiters |
| Long document | Chunk → summarize per section → recursive summary-of-summaries |
| Grounding / accuracy | Provide reference text; use Retrieval for long sources |
| Coding | Use coding-plan endpoint; requirement → architecture → implement |

---

## 11. Sources

- Official prompt-engineering guide (Chinese): https://docs.bigmodel.cn/cn/guide/platform/prompt
- Scenario prompt examples (Chinese): https://docs.bigmodel.cn/cn/best-practice/prompt/talk-prompt
- Core Parameters (international): https://docs.z.ai/guides/overview/concept-param
- Thinking Mode: https://docs.z.ai/guides/capabilities/thinking-mode
- Deep Thinking: https://docs.z.ai/guides/capabilities/thinking
- Function Calling: https://docs.z.ai/guides/capabilities/function-calling
- Structured Output: https://docs.z.ai/guides/capabilities/struct-output
- Context Caching: https://docs.z.ai/guides/capabilities/cache
- Z.ai docs home: https://docs.z.ai/guides/overview/quick-start
- bigmodel.cn docs home: https://docs.bigmodel.cn/
- GitHub org (READMEs, cookbook, Skills): https://github.com/zai-org
