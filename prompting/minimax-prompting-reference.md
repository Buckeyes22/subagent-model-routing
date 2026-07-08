# MiniMax — Prompt Engineering Reference

Provenance: behavioral guidance in this reference was gathered on MiniMax M2.x-era models; current runtime routes MiniMax-M3 — revalidate model-specific behaviors after major MiniMax version bumps.

| Field | Value |
|---|---|
| Vendor | MiniMax |
| Models in scope | MiniMax-M text series (M2, M2.1, M2.5 / M2.5-Lightning, M2.7, **M3**, and **M2-her** for dialogue/role-play); plus speech, image, video, music models |
| Primary access | MiniMax Open Platform API (Anthropic-compatible and OpenAI-compatible), MiniMax Agent, open weights (Modified MIT) |
| Official guidance | **No dedicated text-LLM prompt-engineering guide.** Dedicated prompt guidance exists only for **speech** and **image/video** models. |
| Canonical doc host | `platform.minimax.io` (international; moved from `platform.minimaxi.com`, now the China domain) |
| Compiled | June 2026 |

This is the key fact for MiniMax and the reason this document is structured differently from the other four: **MiniMax does not publish a prompt-engineering guide for its text/agentic models.** This was verified by pulling the platform's full documentation index (`platform.minimax.io/docs/llms.txt`) — the text docs are API-invocation oriented. Official prompt-*specific* guidance exists only for the speech models and for image/video asset generation. Text-model prompting guidance therefore has to be assembled from the **HuggingFace model cards**, the **API docs**, and the **tool-calling guide**, which is what the text sections below do.

---

## 1. Official guidance landscape

For the **text models**, the relevant first-party sources are the **model cards** (`huggingface.co/MiniMaxAI/*`), which carry recommended sampling parameters, the default system prompt, and behavioral notes; the **Model Invocation / text-generation guide** (`platform.minimax.io/docs/guides/text-generation`); the **Tool Calling Guide** linked from each model card; and **prompt-caching** docs. There is no prose guide on how to write prompts for these models.

Dedicated prompt guidance that does exist, for other modalities: a **speech-model prompt guide** (originally `platform.minimaxi.com/docs/guides/prompt/speech-prompt`; the English path moved with the domain migration and the China platform still carries it), and an **image/video asset prompt guide** in the vendor's GitHub Skills repo (`github.com/MiniMax-AI/skills` → `frontend-dev/references/asset-prompt-guide.md`).

Coverage assessment: weakest of the five for text prompting. There is no equivalent to OpenAI's, Alibaba's, or Kimi's prose guide. The practical consequence is captured in §7.

---

## 2. Message format and API surface

MiniMax accepts **both Anthropic-style and OpenAI-style request formats**, and the Anthropic-compatible path is the **recommended** one because it supports thinking blocks, interleaved thinking, and other advanced features.

| Interface | Base URL |
|---|---|
| Anthropic-compatible (recommended) | `https://api.minimax.io/anthropic` |
| OpenAI-compatible | `https://api.minimax.io/v1` |
| OpenAI Responses-compatible | supported via the same platform |

Because the Anthropic Messages format is first-class here, MiniMax models slot into Anthropic-oriented tooling (the model cards document benchmarking with Claude Code as the scaffolding). This compatibility is the basis for the practical recommendation in §7.

---

## 3. Inference parameters (text models)

From the model cards. These are consistent across the recent M2.x generation.

| Parameter | Recommended value |
|---|---|
| `temperature` | **1.0** |
| `top_p` | **0.95** |
| `top_k` | **40** |

Context windows: most M2.x models support **204,800 tokens**; **M3 supports 1,000,000 tokens**; **M2-her** (dialogue/role-play) is **64K**. Both M2.5 and M2.5-Lightning support caching.

---

## 4. Reasoning / thinking control

The text models emit **thinking blocks**, and the Anthropic-compatible path supports **interleaved thinking** (reasoning interspersed with tool calls and text). Models like M2.5 were trained to **reason efficiently and decompose tasks optimally**, completing agentic evaluations substantially faster than prior generations by using fewer reasoning rounds and better token efficiency. When parsing responses on the Anthropic path, handle `thinking` and `text` content blocks separately.

---

## 5. System prompt guidance

MiniMax publishes a **default system prompt** on the model cards rather than prompt-construction guidance. The documented default:

```
You are a helpful assistant. Your name is MiniMax-M2.5 and is built by MiniMax.
```

(The model name is substituted per release, e.g., MiniMax-M2.1, MiniMax-M3.) The cards note that benchmark runs frequently override the default system prompt; there is no canonical "recommended" extended system prompt of the kind Kimi publishes.

---

## 6. Documented model behaviors relevant to prompting

These come from the model cards and are the closest thing MiniMax offers to text-prompting guidance — they describe how the model behaves, which informs how to prompt it.

**Architect-style spec-writing before coding.** M2.5 exhibits a spec-writing tendency: before writing any code, it actively decomposes and plans the features, structure, and UI design of a project from the perspective of an experienced software architect. Prompts that allow or request this planning phase align with the model's trained behavior. The model is documented across the full development lifecycle (0-to-1 system design, 1-to-10 development, 10-to-90 feature iteration, 90-to-100 review and testing), not just frontend demos.

**Parallel tool calling and efficient search.** M2.5 improved parallel tool calling and learned to solve agentic tasks with more precise search rounds and better token efficiency (roughly 20% fewer rounds than M2.1 on several agentic benchmarks). It is documented as generalizing across unfamiliar scaffolding/harness environments.

**Office-work deliverables.** The model was trained to produce deliverable outputs in Word, PowerPoint, and Excel financial-modeling scenarios, with collaboration from finance, law, and social-science professionals.

---

## 7. Practical recommendation for text prompting (non-official)

Flagged explicitly as **not** MiniMax-official: because MiniMax does not publish a text prompt-engineering guide and because its **recommended interface is the Anthropic Messages API** (with first-class thinking and interleaved-thinking support, and benchmark scaffolding via Claude Code), the most directly applicable external prompting reference is **Anthropic's own prompt-engineering documentation**. Structured, role-clear prompting with explicit success criteria, the conventions for interleaved thinking, and Anthropic-style tool-use patterns transfer cleanly to MiniMax because the request format and thinking model are shared. Use the model cards for parameters and the Tool Calling Guide for tool conventions, and apply Anthropic-style prompt structure on top.

---

## 8. Dedicated prompt guidance for non-text modalities

Included for completeness, since this is the prompt guidance MiniMax does publish.

**Speech models (TTS / voice cloning).** The official speech prompt guide stresses that speech prompts must specify not just *what* to say but *how* — tone, emotion, and speaking style; speed, volume, and audio quality; and situational context and audience. An enhanced TTS prompt embeds the delivery direction alongside the spoken text (e.g., instructing a friendly, professional tone before the line to be spoken).

**Image and video models.** The official asset prompt guide (GitHub Skills repo) directs: for **image** prompts, be specific about composition, specify lighting, include style modifiers and technical specs, mention "clean background / web-optimized / high contrast" for web assets, and **never include text in image prompts unless explicitly requested** (AI text rendering is unreliable). For **video** prompts, use MiniMax camera commands in brackets — `[Push in]`, `[Truck left]`, `[Tracking shot]`, and similar.

---

## 9. Quick reference (text models)

| Situation | Action |
|---|---|
| Default sampling | `temperature=1.0`, `top_p=0.95`, `top_k=40` |
| Advanced features (thinking/interleaved) | Use the Anthropic-compatible endpoint |
| Long context | M3 (1M tokens); most M2.x are 204,800 |
| Role-play / dialogue | M2-her (64K) |
| Coding task | Allow/request the architect-style planning phase before code |
| Tool use | Follow the Tool Calling Guide; the model parallelizes tool calls |
| System prompt | Use the model-card default; override freely (no canonical extended prompt) |
| How to write the prompt | No MiniMax guide exists — apply Anthropic-style structured prompting |
| Speech generation | Specify *how* to speak (tone/emotion/speed/volume), not just the text |
| Video generation | Use bracketed camera commands |

---

## 10. Sources

- Text-generation / Model Invocation guide: https://platform.minimax.io/docs/guides/text-generation
- Documentation index (verifies no text prompt guide): https://platform.minimax.io/docs/llms.txt
- Model card (params, system prompt, behaviors): https://huggingface.co/MiniMaxAI/MiniMax-M2.5
- Prompt caching (Anthropic-compatible): https://platform.minimax.io/docs/api-reference/anthropic-api-compatible-cache
- Tool calling guide & deployment: https://github.com/MiniMax-AI/MiniMax-M2.5
- Image/video asset prompt guide (official, non-text): https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/references/asset-prompt-guide.md
- Speech prompt guide (official, non-text; China platform): https://platform.minimaxi.com/docs/guides/prompt/speech-prompt
- Recommended external reference for text prompting (non-official): https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
