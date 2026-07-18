# v0.3 runtime migration

v0.3 keeps the four public shim names and their invocation syntax. Existing callers do not need to change commands, sentinel parsing, provider flags, ledger paths, or timeout handling.

## New prerequisites

- Python 3.11 or newer.
- GNU `timeout` or `gtimeout`, retained as a compatibility prerequisite for the existing exit-127/no-ledger behavior.

Re-run `scripts/install.sh` so `model-routing` is linked beside the four shims. The Python package stays in the source checkout; the symlinked entrypoint resolves that checkout through its real path.

## Additive behavior

- Private structured run records under the XDG state directory.
- `model-routing runs list|show|logs|cleanup`.
- Portable lifecycle hooks from the XDG config directory.
- `CODEX_BIN` executable override.
- `--routing-retain-prompt` explicit prompt retention.
- Optional extended ledger fields, while legacy mandatory fields remain unchanged.

## Compatibility notes

The migration deliberately preserves early-error and ledger asymmetries, including orphaned `started` rows. The successful and child-error suffix remains the raw bytes `\nSHIM-DONE exit=<n>\n`; early usage/prerequisite failures retain the plain sentinel without the leading blank line.

Claude Code and Grok Build still receive prompts on argv, so same-user process inspection exposure is unchanged. Codex and OpenCode continue to receive prompts over stdin.

The v0.4 doctor/worktree features and v0.5 workflow/live-discovery features are not included in the historical v0.3 surface; see their later migration guides.
