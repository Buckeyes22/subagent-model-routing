# OpenAI (Codex / GPT) — Prompt Engineering Reference

| Field | Value |
|---|---|
| Vendor | OpenAI |
| Models in scope | GPT-5.x series (general API/ChatGPT), Codex-tuned models (e.g., `gpt-5.3-codex`), legacy GPT-4.1 |
| Primary access | OpenAI API (Responses + Chat Completions), ChatGPT, Codex (CLI / IDE extension / app / web / SDK) |
| Official guidance | Extensive and actively maintained — dedicated prompt-engineering, model-version prompt-guidance, and Codex-specific tracks |
| Canonical doc host | `developers.openai.com` (migrated from `platform.openai.com`); Help Center at `help.openai.com` |
| Compiled | June 2026 |

This document consolidates OpenAI's official prompting guidance for its text and agentic-coding models. OpenAI maintains the most complete first-party prompting documentation of the major vendors and splits it into two tracks: a general GPT track (prompt engineering + model-version-specific guidance) and a Codex track (agentic coding). Both are covered here.

---

## 1. Official guidance landscape

OpenAI publishes prompting guidance across several distinct, first-party surfaces. The split matters because the model-version-specific guidance changes with each release and supersedes older general advice where they conflict.

The **general prompt-engineering guide** (`developers.openai.com/api/docs/guides/prompt-engineering`, legacy mirror at `platform.openai.com/docs/guides/prompt-engineering`) covers cross-model strategies — agentic and long-running rollouts, role and workflow framing for coding agents, structured tool use, and front-end engineering prompt categories. The **model-version prompt-guidance page** (`developers.openai.com/api/docs/guides/prompt-guidance`) is the page that tracks current-generation behavior changes; it focuses on what to change for the latest GPT-5.x models, including reasoning-effort selection by task shape, output and citation formats, dependency-aware tool rules, and explicit completion criteria. The **Codex prompting page** (`developers.openai.com/codex/prompting`) and **Codex best-practices guide** (`developers.openai.com/codex/learn/best-practices`) cover agentic coding specifically. Two Help Center articles round out the set for API and ChatGPT users respectively.

OpenAI also maintains an **`llms.txt`-style structured doc map**, a **Prompt Optimizer** tool (`developers.openai.com/api/docs/guides/prompt-optimizer`), reasoning best-practices (`developers.openai.com/api/docs/guides/reasoning-best-practices`), and a **Cookbook** with executable prompting examples. Codex can apply documentation changes directly via the OpenAI Docs Skill, downloadable from OpenAI's skills repository.

Coverage assessment: comprehensive for text generation, reasoning, agentic coding, tool use, and structured output. This is the reference standard against which the other four vendors in this set should be measured.

---

## 2. Message format and API surface

OpenAI models are driven through role-structured messages. The **Responses API** is the current recommended interface and is preferred for long-running and stateful GPT-5.x sessions; the **Chat Completions API** remains available and is the format most third-party tooling targets. System/developer messages define behavior and persona; user messages carry the task; assistant messages and tool calls follow.

For long-running GPT-5.x sessions in the Responses API, OpenAI documents **compaction** (`developers.openai.com/api/docs/guides/compaction`) as first-class guidance for multi-hour reasoning and long conversations, alongside prompt caching and token counting.

---

## 3. Inference and control parameters

GPT-5.x exposes two prompting-adjacent control parameters beyond the message content itself, which are the highest-leverage knobs after the prompt text.

| Parameter | Values | Purpose |
|---|---|---|
| `reasoning_effort` | none / low / medium / high (and model-specific higher tiers) | Controls depth of internal reasoning. Choose by task shape, not by difficulty alone. |
| `verbosity` | low / medium / high | Controls output length independent of reasoning depth. |
| `temperature` / `top_p` | 0–2 / 0–1 | Standard sampling controls. OpenAI recommends adjusting one, not both. |

On reasoning effort selection, the official guidance is to **start with medium or higher for research-heavy workloads** such as long-context synthesis, multi-document review, conflict resolution, and strategy writing, and that a well-engineered prompt at medium can extract substantial performance. For workloads depending on nuanced interpretation of implicit requirements, ambiguity, or cancelled-tool-call recovery, start at low or medium rather than the maximum. For current-generation models, the lowest effort tiers already perform well on action-selection and tool-discipline tasks.

The documented discipline for tuning is **one change at a time**: switch model first, pin `reasoning_effort`, then run evals before changing anything else.

---

## 4. Reasoning control and the initiative nudge

When a GPT-5.x model is too literal or stops at the first plausible answer, OpenAI's documented remedy is to add an **initiative nudge before raising reasoning effort**, rather than reaching for maximum effort immediately. The canonical nudge block from the prompt-guidance page instructs the model not to stop at the first plausible answer, to look for second-order issues, edge cases, and missing constraints, and to perform at least one verification step when the task is safety- or accuracy-critical:

```
<dig_deeper_nudge>
- Don't stop at the first plausible answer.
- Look for second-order issues, edge cases, and missing constraints.
- If the task is safety or accuracy critical, perform at least one verification step.
</dig_deeper_nudge>
```

This pattern is the recommended first intervention for under-eager behavior because it is cheaper than raising reasoning effort and more targeted.

---

## 5. Default style and persona (GPT-5.5)

GPT-5.5's default style is **efficient, direct, and task-oriented**. For production systems this is desirable: responses stay focused, behavior is easier to steer, and the model avoids conversational padding. The official guidance distinguishes two things to define explicitly for customer-facing, support, and coaching products: **personality** (how the assistant sounds — tone, warmth, directness, formality, humor, empathy, polish) and **collaboration style** (how it works with the user). Both should be specified separately rather than conflated.

---

## 6. Core prompting techniques (GPT track)

OpenAI's general guidance emphasizes that GPT-5.x models benefit from **precise instructions that explicitly provide the logic and data required to complete the task in the prompt itself**, rather than relying on the model to infer them.

For coding tasks specifically, the documented best practices are to define the agent's role, enforce structured tool use with examples, require thorough testing for correctness, and set Markdown standards for clean output. The model should be framed as a software-engineering agent with well-defined responsibilities.

For **front-end engineering in larger codebases**, OpenAI documents adding these categories of instruction to prompts: *Principles* (visual quality standards, modular/reusable components, design consistency), *UI/UX* (typography, colors, spacing/layout, interaction states, accessibility), *Structure* (file/folder layout for integration), *Components* (reusable wrapper examples, backend-call separation), *Pages* (templates for common layouts), and *Agent Instructions* (confirm design assumptions, scaffold projects, enforce standards, integrate APIs, test states, document code).

For agentic and long-running rollouts with GPT-5.5, three core practices are emphasized: plan tasks thoroughly to ensure complete resolution, provide clear preambles for major steps, and avoid upfront plans and preambles where they would interrupt the rollout (this last point is sharpened in the Codex track below).

### Legacy GPT-4.1 agentic reminders

The GPT-4.1 prompting guidance remains relevant for that model and introduced three reminders worth retaining when targeting 4.1: **persistence** (keep going until the query is fully resolved before yielding), **tool-calling** (use tools to gather information rather than guessing), and **planning** (plan before each tool call and reflect after). GPT-4.1 also follows instructions more literally than its predecessors, and for long-context tasks benefits from instruction placement at both the start and the end of the context.

---

## 7. Codex (agentic coding) prompting

Codex is OpenAI's agentic coding system. The governing principle in the official guidance is to **treat Codex less like a one-off assistant and more like a teammate you configure and improve over time**. Codex is already strong enough to be useful even when the prompt is imperfect; clear prompting is not required to get value, but it makes results more reliable, especially in larger codebases and higher-stakes tasks.

### The four prompt elements

The Codex best-practices guidance defines four elements of an effective prompt: **Goal**, **Context**, **Constraints**, and **Completion Criteria**. Consciously including these improves the accuracy of Codex's understanding and the quality of its output. For complex tasks, use **plan mode** to have Codex propose a plan before executing.

### The Codex working loop

When you submit a prompt, Codex works in a loop: it calls the model and then performs the actions indicated by the model output — file reads, file edits, and tool calls — ending when the task is complete or you cancel it. The unit of interaction is a **thread** (a session of your prompts plus model outputs and tool calls); threads can contain multiple prompts, can run concurrently (avoid having two threads modify the same files), and can be resumed later.

### Documented prompting tips for Codex

Codex produces higher-quality outputs when it can **verify its work**, so prompts should include steps to reproduce an issue, validate a feature, and run linting and pre-commit checks. Codex handles complex work better when it is **broken into smaller, focused steps** — smaller tasks are easier for Codex to test and for you to review. When task decomposition is unclear, the recommended move is to **ask Codex to propose a plan** rather than specifying it yourself.

### Reasoning levels for Codex

The default reasoning level should be **Medium to High**, with **Extra High reserved for extremely complex tasks**. The Codex models advance behavior changes that favor faster, more token-efficient agentic coding, higher long-running autonomy, first-class compaction for multi-hour reasoning, and guidance to **avoid upfront plans and preambles that can interrupt Codex rollouts**.

### Durable context: AGENTS.md

The single most important configuration file is **`AGENTS.md`**, which encodes durable, project-level guidance for Codex: what commands to run, what standards to follow, and what to avoid. A typical `AGENTS.md` specifies project overview, commands (test/lint/build), and conventions (component patterns, file placement, validation libraries, testing requirements). The documented mental model is to invest upfront in context files and prompt structure, then reuse that investment across every task: start with the right task context, use `AGENTS.md` for durable guidance, configure Codex to match your workflow, connect external systems with MCP, turn repeated work into Skills, and automate stable workflows.

---

## 8. Documented pitfalls

The official guidance flags several recurring failure modes. Over-eager early stopping (mitigated by the initiative nudge before raising reasoning effort). Conflating personality with collaboration style in conversational products. Raising reasoning effort as the first intervention rather than improving the prompt. Allowing two concurrent Codex threads to modify the same files. Omitting verification steps from coding prompts, which removes Codex's ability to self-check. Inserting upfront plans and preambles into Codex prompts where they interrupt the rollout. Changing more than one variable at a time when tuning, which destroys the ability to attribute changes to a cause.

---

## 9. Quick reference

| Situation | Action |
|---|---|
| Research/synthesis task | `reasoning_effort` medium or higher; explicit output + citation format |
| Model too literal / stops early | Add `dig_deeper_nudge` block before raising effort |
| Output too long/short | Adjust `verbosity`, not `reasoning_effort` |
| Conversational product | Define personality and collaboration style separately |
| Long-running session | Responses API + compaction |
| Codex task | Specify Goal, Context, Constraints, Completion Criteria |
| Codex, unclear scope | Ask Codex to propose a plan (plan mode) |
| Codex, reliable results | Include reproduce/validate/lint steps; break into small steps |
| Codex, durable standards | Put them in `AGENTS.md`, not in every prompt |
| Codex reasoning default | Medium–High; Extra High only for extreme complexity |
| Tuning anything | Change one variable, run evals, then change the next |

---

## 10. Sources

All first-party. Migration from `platform.openai.com` to `developers.openai.com` is ongoing; prefer the `developers.openai.com` URLs.

- General prompt engineering: https://developers.openai.com/api/docs/guides/prompt-engineering (legacy mirror: https://platform.openai.com/docs/guides/prompt-engineering)
- Model-version prompt guidance (current GPT-5.x): https://developers.openai.com/api/docs/guides/prompt-guidance
- Prompting overview: https://developers.openai.com/api/docs/guides/prompting
- Reasoning best practices: https://developers.openai.com/api/docs/guides/reasoning-best-practices
- Prompt optimizer: https://developers.openai.com/api/docs/guides/prompt-optimizer
- Compaction (long sessions): https://developers.openai.com/api/docs/guides/compaction
- Codex prompting: https://developers.openai.com/codex/prompting
- Codex best practices: https://developers.openai.com/codex/learn/best-practices
- Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- Codex workflows: https://developers.openai.com/codex/workflows
- Help Center (API): https://help.openai.com/en/articles/6654000-best-practices-for-prompt-engineering-with-the-openai-api
- Help Center (ChatGPT): https://help.openai.com/en/articles/10032626-prompt-engineering-best-practices-for-chatgpt
- Cookbook (executable examples): https://developers.openai.com/cookbook
