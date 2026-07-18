---
description: Build a Workflow DAG that delegates each node's work to a non-Claude model (GPT/Grok/Kimi/GLM/MiniMax/Qwen) via the shims.
argument-hint: [task to orchestrate as a DAG across external models]
---

First **invoke the `subagent-model-routing` skill** (load it via the Skill tool), then follow it to orchestrate the task below.

**Mechanism is mandatory — clear this before writing anything.** If the task has *dependency edges* it is a DAG, and you MUST execute it via the **`Workflow` tool** (`Workflow({ scriptPath })`). Do **NOT** run a DAG as direct `Agent({subagent_type:'…-shim'})` calls, direct `Bash ~/.claude/scripts/*-shim.sh` invocations, or inline work — that is the **transport leak** (the work may reach the external models, but the DAG the user asked for never existed; "launched as shells" / "still on Opus"). If the task has *no* dependency edges, it is **not** a DAG — use the Part B flat-dispatch half of `subagent-model-routing` directly and say so.

Then follow the skill's gates: every node carries a namespaced codex, kimi, grok, or opencode shim `agentType` and `model: 'sonnet'`, authored **only** through the `codex()` / `grok()` / `kimi()` / `glm()` / `minimax()` helpers (no bare `agent()`); run the leak audit before launch; split judgment edges into separate workflow segments; pilot before fan-out.

Task: $ARGUMENTS
