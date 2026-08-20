# Qwen provider — design

Date: 2026-08-19. Status: approved (design agreed in-session).

## Goal

Add `qwen` as a sixth first-class provider so Qwen Code dispatches gain the full
contract the other five providers have: SHIM-DONE sentinel, run records, ledger
attribution, doctor checks, and tripwire coverage. Replaces the previous
machine-local `qwen-shim.sh` and the doctrine that Qwen routes only through OpenCode.

## Decisions

- **Adapter modeled on Kimi.** Kimi Code is a Qwen Code fork; the CLI contract
  matches: prompt via `--prompt <text> --output-format text`, reserved flags
  (`-p`, `--prompt`, `--output-format`) rejected, incompatible approval flags
  (`-y`, `--yolo`, `--approval-mode`) rejected from callers.
- **Model attribution only.** `-m/--model` override → env `QWEN_MODEL` →
  `~/.qwen/settings.json` (`model.name` or `model`) → `qwen-default`. The
  adapter never injects `-m`; Qwen Code's own config decides.
- **Unrestricted mode** (`SUBAGENT_MODEL_ROUTING_UNRESTRICTED`, default on)
  appends `--yolo`. Restricted mode leaves Qwen's approval policy alone.
- **Endpoint and secret never enter the repo.** `~/.qwen/.env` (mode 600)
  carries `OPENAI_API_KEY`, `OPENAI_BASE_URL` (the machine-local
  OpenAI-compatible endpoint), and `QWEN_MODEL` (the served model's alias).
  (Deviation discovered at verification: Qwen Code 0.21.14 dropped the
  `QWEN_AUTH_TYPE`/`QWEN_OPENAI_*` names; auth type "openai" is inferred when
  `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`-or-`QWEN_MODEL` are
  all set.) The repo is public; registry entries stay endpoint-free like every
  other provider.
- **Registry**: add `qwen` provider (binary candidates `qwen` on PATH plus the
  npm-global path, `binaryOverrideEnv: QWEN_BIN`, no effort control, no auth
  probe — auth is llama.cpp's Bearer key, validated at dispatch). Remove the
  `qwen*` patterns from OpenCode's route families so routing is unambiguous.
- **Shim**: `scripts/qwen-shim.sh`, thin wrapper identical in shape to
  `grok-shim.sh` (`exec model-routing _shim qwen`). Added to `install.sh`.
- **Docs/ledger**: update `ledger/qwen.md` in all three plugin packages
  (currently claims OpenCode transport), README provider table.

## Error handling (inherited from the shared runtime)

Missing binary → 127 + `SHIM-DONE exit=127`; nonzero qwen exit propagates
through the sentinel; truncation caught by tripwires; every dispatch recorded
in the run store and ledger.

## Testing

Extend adapter/registry parity tests with qwen cases (TDD: tests first), run
the full suite, `validate_registry.py`, `sync_routes.py --check`, then a live
`pong` dispatch against the configured endpoint through the installed shim.
