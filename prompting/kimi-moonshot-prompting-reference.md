# Kimi (Moonshot AI) — Prompt Engineering Reference

| Field | Value |
|---|---|
| Vendor | Moonshot AI |
| Models in scope | Kimi K2.x series (K2, K2-Instruct, K2.5, K2.6, K2.7, K2.7-Code) — MoE, ~1T total / ~32B active params |
| Primary access | Kimi Open Platform API (OpenAI-compatible), Kimi.com / Kimi app, Kimi Code CLI, open weights (Modified MIT) |
| Official guidance | A dedicated **Best Practices for Prompts** page exists and is reasonably complete |
| Canonical doc host | `platform.moonshot.ai` and `platform.kimi.ai` (mirror); `platform.kimi.com` for China |
| Compiled | June 2026 |

Moonshot publishes a genuine, dedicated prompt best-practices page. The platform has rebranded toward the **Kimi** name; `platform.moonshot.ai` and `platform.kimi.ai` resolve to the same documentation with identical paths, and `platform.kimi.com` serves the China site. The structure of the official guide closely mirrors the canonical OpenAI prompt-engineering taxonomy.

---

## 1. Official guidance landscape

The dedicated guide is **"Best Practices for Prompts"** at `/docs/guide/prompt-best-practice`. It is supported by several adjacent official pages: an **agent-construction guide** (`use-kimi-k2-to-setup-agent`), a **benchmarking best-practices** page (`benchmark-best-practice`), a **tool-calling guide**, an **OpenAI-to-Kimi migration** guide (`migrating-from-openai-to-kimi`), and the per-model **HuggingFace model cards** (`huggingface.co/moonshotai`) which carry recommended sampling parameters and the canonical system prompt.

Coverage assessment: solid for general technique, system-prompt construction, tool use, and benchmarking reproducibility. The guide itself is generic (it parallels OpenAI's), but the agent-setup and tool-calling pages contain genuinely Kimi-specific operational guidance worth reading.

---

## 2. Message format and API surface

Kimi is **OpenAI-API-compatible**. Base URL is `https://api.moonshot.ai/v1`; existing OpenAI Python/Node SDKs work against it. A documented API difference: **`tool_choice="required"` is not currently supported** — and if you set `temperature=0` for deterministic output, you must set `n=1` (or leave it default). Usage information (`prompt_tokens` / `completion_tokens` / `total_tokens`) is placed in the end data block when streaming.

---

## 3. Inference parameters

From the model cards and migration guidance. The critical point is that **recommended temperature varies by model family** — there is no single default.

| Model | Recommended temperature | Notes |
|---|---|---|
| Kimi-K2-Instruct | **0.6** | Documented default on the model card |
| kimi-k2-turbo-preview | **0.6** | From migration guidance |
| Older Kimi models | **0.3** | Safe default |
| Deterministic runs | `temperature=0` | Must also set `n=1` |

**Streaming is strongly recommended** for reliability: long outputs can take minutes, and idle TCP connections may be terminated by firewalls, load balancers, or NAT gateways. Non-streaming mode can cause random mid-connection interruptions.

---

## 4. System prompt guidance

Moonshot publishes a **canonical recommended system prompt**. For most cases the short form is adequate and reproduces benchmarks; the longer form is recommended when using the API, for safety reasons.

Short form (default; also the model's chat-template default):

```
You are Kimi, an AI assistant created by Moonshot AI.
```

Longer form (recommended for API use):

```
You are Kimi, an artificial intelligence assistant provided by Moonshot AI. You are
more proficient in Chinese and English conversations. You provide users with safe,
helpful, and accurate answers. At the same time, you will refuse to answer any
questions involving terrorism, racism, or explicit violence. Moonshot AI is a proper
noun and should not be translated into other languages.
```

The official guidance notes that K2 should follow essentially any prompt, so the system prompt is a default rather than a hard requirement.

---

## 5. Core prompting techniques (official guide)

The guide is organized into three sections that parallel the standard taxonomy.

### Write clear instructions

The framing is that the model cannot read your mind: if output is too long, ask for brevity; too simple, request expert-level writing; wrong format, show the format you want. The less the model has to guess, the better the result. Specific techniques follow.

**Include more detail in the request** for more relevant responses — ensure the input contains all important details and context. (The guide's example contrasts "How to add numbers in Excel?" with a fully-specified request naming the operation, the table scope, and the target column.) **Assign a role** via the system message for more accurate output. **Use delimiters** — triple quotes, XML tags, or section headings — to separate parts of the input that require different processing (its example feeds two `<article>...</article>` blocks for comparison). **Define the steps** needed to complete the task explicitly; writing the steps out makes the model easier to follow and improves output (e.g., "Step one: summarize the triple-quoted text with the prefix 'Summary:'. Step two: translate that summary and prefix 'Translation:'"). **Provide examples** of desired output — general-guidance examples are usually more efficient than enumerating all task permutations; this is the few-shot pattern, used especially when the target style is hard to describe explicitly. **Specify output length** — target a number of words, sentences, paragraphs, or bullet points, with the documented caveat that exact word counts are imprecise and the model hits paragraph/bullet targets more reliably than word-count targets.

### Provide reference text

Supply credible information related to the query and instruct the model to use it. A documented anti-hallucination pattern: "Answer the question using the provided article (enclosed in triple quotes). If the answer is not found in the article, write 'I can't find the answer.'"

### Break down complex tasks

**Categorize the query first** — for tasks needing a large set of independent instructions across scenarios, classify the query type and use the classification to select which instructions apply (the example routes a support query into a troubleshooting branch with device-model-specific steps). **Summarize or filter prior turns** in long-running dialogue applications — because context is fixed, trigger a summarization query once input reaches a threshold and fold the summary into the system message, or summarize asynchronously. **Chunk and recursively summarize long documents** — summarize each chapter, aggregate partial summaries into a summary-of-summaries, and repeat; include summaries of preceding chapters when later content depends on them.

---

## 6. Tool use and agentic prompting

Kimi K2 has strong native tool-calling. The operational guidance is specific and contrasts with how some other models are prompted: **pass the list of available tools in each request and let the model autonomously decide when and how to invoke them**. Critically, the agent-setup guide warns **not to specify the tools or their usage in the System Prompt**, because doing so can interfere with the model's autonomous decision-making. Tool parsing relies on Kimi's native tool-parsing logic in the inference engine; for streaming output and manual parsing, follow the Tool Calling Guide.

The recommended pre-build step for agents is to **decompose the target task**, which simultaneously improves prompt engineering and tool selection. Kimi also offers a set of official built-in tools that can be integrated directly.

### Thinking mode and tool interaction

When the `thinking` parameter is `{"type": "enabled"}` and tools are in use, **`tool_choice` can only be `"auto"` or `"none"`** (default `"auto"`) to avoid conflicts between reasoning content and the tool specification. Note also that the official built-in `$web_search` tool was documented as temporarily incompatible with K2.5 thinking mode — the workaround is to disable thinking before using `$web_search`.

---

## 7. Benchmarking and reproducibility

Moonshot's benchmarking best-practices page is worth following whenever output stability matters, not just for benchmarks. Use the **official API** — some third-party endpoints show noticeable accuracy drift; the **Kimi Vendor Verifier (KVV)** helps select high-accuracy third-party services. Use **streaming** for reliability on long outputs. For reasoning benchmarks, set `max_tokens = 128k` and run a large sample count (hundreds to ~1000) to reduce variance. Remember that **temperature is not consistent across model families** — set it per the model card.

---

## 8. Quick reference

| Situation | Action |
|---|---|
| Set temperature | Per model: 0.6 for K2-Instruct/turbo, 0.3 for older; `n=1` if `temperature=0` |
| Reliability on long outputs | Enable streaming |
| Steering | Use the canonical Kimi system prompt (long form for API) |
| Tool use | Pass tools per request; let the model decide; do **not** list tools in the system prompt |
| Thinking + tools | `tool_choice` must be `auto` or `none` |
| `$web_search` on K2.5 | Disable thinking first |
| Anti-hallucination | Instruct "if not in the text, say 'I can't find the answer'" |
| Hard-to-describe style | Few-shot examples |
| Long document | Chunk → summarize → recursive summary-of-summaries |
| Long dialogue | Summarize earlier turns into the system message at a threshold |
| Stable/reproducible output | Official API + KVV-verified vendors + streaming |

---

## 9. Sources

- Best Practices for Prompts: https://platform.moonshot.ai/docs/guide/prompt-best-practice (mirror: https://platform.kimi.ai/docs/guide/prompt-best-practice)
- Agent setup guide: https://platform.moonshot.ai/docs/guide/use-kimi-k2-to-setup-agent
- Benchmarking best practices: https://platform.moonshot.ai/docs/guide/benchmark-best-practice
- OpenAI-to-Kimi migration: https://platform.moonshot.ai/docs/guide/migrating-from-openai-to-kimi
- Agent support / coding-tool setup: https://platform.moonshot.ai/docs/guide/agent-support
- Model card (params + system prompt): https://huggingface.co/moonshotai/Kimi-K2-Instruct
- GitHub (tool-calling guide, deployment): https://github.com/MoonshotAI/Kimi-K2
- China platform: https://platform.kimi.com
