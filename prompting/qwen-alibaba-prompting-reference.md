# Qwen (Alibaba) — Prompt Engineering Reference

| Field | Value |
|---|---|
| Vendor | Alibaba — served via **Alibaba Cloud Model Studio** (DashScope) |
| Models in scope | Qwen3.x text series (Qwen-Max / Plus / Turbo / Flash), Qwen-Coder, QwQ reasoning line, open weights (`QwenLM`, mostly Apache-2.0) |
| Primary access | Model Studio API (OpenAI-compatible / DashScope), Qwen Chat, open weights via HuggingFace / ModelScope |
| Official guidance | A dedicated, example-heavy **Text-to-text prompt guide** exists in Model Studio |
| Canonical doc host | `alibabacloud.com/help/en/model-studio` (English); `help.aliyun.com` (Chinese / DashScope) |
| Compiled | June 2026 |

Alibaba publishes a genuine, dedicated, English-language prompt-engineering guide for its text models under Model Studio. It is the most **example-driven** of the five vendors' guides — nearly every technique is taught through full before/after prompt-and-output pairs rather than abstract rules. Its centerpiece is a named prompt framework.

---

## 1. Official guidance landscape

The dedicated guide is the **"Text-to-text prompt guide"** at `alibabacloud.com/help/en/model-studio/prompt-engineering-guide` (last updated March 2026 at time of writing). It sits inside Model Studio's **Best Practices** section and is supported by Model Studio's broader tooling, including a **Prompt IDE / prompt-optimization** capability for comparing prompt variants across models, plus the **per-model docs and HuggingFace/ModelScope model cards** for the open-weight Qwen releases (which carry sampling defaults and the thinking-mode controls described in §4).

Coverage assessment: strong for general technique and prompt structuring, taught concretely. The guide is model-agnostic across the Qwen line (it does not single out per-model quirks); model-specific behavior such as Qwen3's hybrid thinking switches lives in the model documentation, covered separately below.

---

## 2. Message format and API surface

Qwen is served through Model Studio with an **OpenAI-compatible** endpoint (the DashScope-compatible mode), so the OpenAI Python SDK works directly against it; a native DashScope SDK also exists. Standard role-structured messages apply.

---

## 3. The two governing principles

The guide is built on two top-level moves: **design** clear prompts, then **optimize** them.

### Build clear and specific prompts

The framing is the colleague analogy: a task assigned in one vague sentence yields output far from expectations, while supplying clear purpose, suggested direction, and execution strategy produces high-standard results. The same holds for the model. The guide states plainly that **building a clear and specific prompt is the single most important step** in leveraging an LLM. Its worked examples contrast a vague product-promotion request against a specific one that names the product, enumerates the selling points to highlight, specifies the platform and length constraints, and states the desired effect on the reader; and a loosely-specified PHP task against one that enumerates required coverage (implementation steps, boundary-condition analysis, error handling, security considerations, performance optimization).

### Use a prompt framework

To systematize "clear and specific," Alibaba recommends a named **prompt framework** with six elements. This is the structural core of the official guidance:

| Element | Tag used in examples | Purpose |
|---|---|---|
| **Context** | `#Background#` | Background closely related to the task, so the model understands the scenario and stays relevant |
| **Objective** | `#Purpose#` | The specific task you expect completed — precise instructions focus the model |
| **Style** | `#Style#` | The writing style (a specific person, school, or type of expert) |
| **Tone** | `#Tone#` | The register — formal, humorous, warm, caring — to suit the scenario |
| **Audience** | `#Audience#` | The target reader group (professionals, beginners, children) so the model adjusts depth and language |
| **Response** | `#Outputs#` | The exact output form — list, JSON, professional analysis report — so results feed downstream use directly |

The documented value of the framework is that it forces consideration of **style, tone, and audience** — the three elements typically missing from naive prompts — and produces output that is more targeted, more detailed, and more engaging. The guide is explicit that the framework is not rigid: add or remove elements per task.

---

## 4. Reasoning / thinking control (Qwen3 model docs)

This is documented in the **Qwen model documentation and model cards**, not the Model Studio prompt guide, and is flagged as such. The Qwen3 generation introduced a **hybrid thinking** design: reasoning can be toggled with an `enable_thinking` parameter, and steered inline with the soft switches **`/think`** and **`/no_think`** placed in the prompt. Use thinking for complex reasoning, math, and multi-step planning; disable it for latency-sensitive or simple tasks. The dedicated **QwQ** line is reasoning-first. Per-model sampling defaults (temperature, top_p, top_k, presence penalty) are published on each model's HuggingFace / ModelScope card and should be taken from there rather than assumed.

---

## 5. Optimization techniques (official guide)

Once a clear, framework-structured prompt exists, the guide gives three optimization tips, each taught through full examples.

### Tip 1 — Provide output examples

Including examples of expected output lets the model imitate the standards, format, concepts, grammar, and tone you require, and makes results across multiple generations **more consistent**, stabilizing performance. The guide's example augments a social-post prompt with an explicit `#Tone and Style#` section containing several named rhetorical formulas (e.g., "personally tested + who benefits," "problem → reason → solution," "unique insight → analysis → recommendation," "personal experience → results showcase"), and the model's output visibly adopts those patterns. This is few-shot/imitation prompting framed as an optimization step.

### Tip 2 — Set steps for tasks

For complex tasks, reminding the model how to complete the task is essential. The guide demonstrates this on a multi-step word problem by adding an explicit `#Task Steps#` block (first compute the catch-up time and distance; then the remaining distance and time; then the arrival time). With the steps supplied, the model decomposes the problem in that exact order and reaches the correct answer, where an unstructured prompt is more error-prone. The lesson generalizes: when a task has a known solution procedure, encode the procedure as numbered steps in the prompt.

### Tip 3 — Use separators to distinguish units

When constructing complex prompts, use specific separators to delimit content units; this significantly improves the model's ability to parse the prompt correctly, and matters more as complexity rises. The documented guidance is to use **unique character combinations rare in natural language** — `###`, `===`, `>>>` — because their high recognizability lets the model treat them as boundary markers rather than ordinary punctuation. (The example wraps a movie review in `###` before asking for a summary.)

---

## 6. Documented pitfalls

The guide's failure modes are framed implicitly through its before/after contrasts. Vague, under-specified prompts produce generic output lacking detail and audience fit. Omitting style, tone, and audience — the elements the framework is designed to surface — yields output that performs adequately but does not target the intended reader. Letting the model attempt complex multi-step tasks without an explicit step decomposition raises the error rate. Relying on ordinary punctuation instead of high-recognizability separators degrades parsing of complex prompts. Expecting precise word-count adherence (the model handles structural targets better than exact counts) — a caveat consistent across vendors.

---

## 7. Quick reference

| Situation | Action |
|---|---|
| Any non-trivial task | Structure with the six-element framework (Context, Objective, Style, Tone, Audience, Response) |
| Generic / off-target output | Add the missing Style, Tone, and Audience elements |
| Consistency across generations | Provide output examples (Tip 1) |
| Known multi-step procedure | Encode it as `#Task Steps#` (Tip 2) |
| Complex prompt with mixed content | Delimit units with `###`, `===`, or `>>>` (Tip 3) |
| Complex reasoning / math | Enable thinking; use `/think`; consider QwQ |
| Latency-sensitive | `/no_think` or `enable_thinking=false` |
| Sampling defaults | Take from the per-model HuggingFace / ModelScope card |
| Comparing prompt variants | Use Model Studio's Prompt IDE / optimizer |

---

## 8. Sources

- Text-to-text prompt guide (English): https://www.alibabacloud.com/help/en/model-studio/prompt-engineering-guide
- Model Studio Best Practices index: https://www.alibabacloud.com/help/en/model-studio/use-cases/
- Model Studio User Guide (Models): https://www.alibabacloud.com/help/en/model-studio/model-user-guide/
- DashScope (Chinese) docs: https://help.aliyun.com/zh/model-studio/
- Open-weight models, cards, and technical reports: https://github.com/QwenLM and https://huggingface.co/Qwen
