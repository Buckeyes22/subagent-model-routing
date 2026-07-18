# xAI Grok 4.5 and Grok Build prompting reference

This is the canonical project reference for prompts sent through `grok-shim.sh`. It is grounded only in official xAI documentation on `docs.x.ai` and separates documented behavior from repository guidance.

## Model and harness

Grok 4.5 uses the model ID `grok-4.5`. xAI describes it as a frontier model for coding, agentic, and knowledge work, and documents it as the default model in Grok Build. Grok Build is an agentic coding harness whose CLI executable is `grok`.

The repository route is:

```bash
~/.claude/scripts/grok-shim.sh <prompt-file> [grok flags]
```

The shim converts the prompt file (or stdin via `-`) into Grok Build's headless `-p` request, selects `grok-4.5` unless the caller passes `-m`/`--model`, requests plain output, disables automatic CLI updates for the scripted run, and preserves the shared `SHIM-DONE exit=<n>` and JSONL-ledger contracts.

## Prompt shape for routed coding work

xAI presents Grok Build as an agentic coding tool that can inspect a repository, edit files, run commands, and work with tools. For reliable routed work, this repository therefore recommends a concrete execution contract:

1. State the objective and relevant repository context.
2. Name allowed files or scope boundaries and any actions requiring confirmation.
3. Specify the expected edits or analysis output.
4. Provide exact validation commands and completion criteria.
5. Require a concise report of changed artifacts and check results.

This five-part prompt shape is project guidance inferred from the documented agentic workflow; xAI does not present it as a required template.

Example:

```text
Objective: Fix the parser regression described below.
Context: The implementation is in src/parser.ts and tests are in test/parser.test.ts.
Constraints: Stay within those files. Do not change public APIs or dependencies.
Work: Inspect the current implementation, make the smallest correct fix, and add a regression test.
Validation: Run npm test -- parser.test.ts and npm run typecheck.
Completion: Leave the workspace with the fix and test applied, then report changed files and command results.
```

## Reasoning effort

Grok 4.5 supports `low`, `medium`, and `high` reasoning effort; xAI documents `high` as the default. Keep the default for difficult debugging, architecture, and verification. Use `--effort low` or `--effort medium` when latency matters and the task is routine or tightly specified:

```bash
~/.claude/scripts/grok-shim.sh /tmp/task.md --effort medium
```

Treat effort as a cost/latency versus depth control, not a substitute for a clear task contract.

## Authentication and unattended execution

Interactive users can authenticate with the browser flow started by `grok login`; device authorization is available with `grok login --device-auth`. Headless environments can provide `XAI_API_KEY`.

Grok Build's CLI sandbox is off by default. This project's unrestricted mode also passes `--always-approve` so an unattended child does not pause for an approval prompt. Set `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0` to retain Grok Build's approval behavior, and forward an explicit sandbox policy such as `--sandbox workspace` when isolation is desired.

## Official sources

- [Grok Build overview](https://docs.x.ai/build/overview)
- [Grok Build CLI reference](https://docs.x.ai/build/cli/reference)
- [Headless mode and scripting](https://docs.x.ai/build/cli/headless-scripting)
- [Grok 4.5](https://docs.x.ai/developers/grok-4-5)
- [Grok Build enterprise security and authentication](https://docs.x.ai/build/enterprise)
