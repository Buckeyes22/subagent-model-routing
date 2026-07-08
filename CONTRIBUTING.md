# Contributing

Issues and pull requests are welcome.

## Local checks

Run the same checks CI runs before pushing:

```bash
for s in scripts/*.sh; do bash -n "$s"; done
[ "$(bash scripts/codex-shim.sh 2>&1 | tail -1)" = "SHIM-DONE exit=64" ]
[ "$(bash scripts/opencode-shim.sh 2>&1 | tail -1)" = "SHIM-DONE exit=64" ]
python3 -m py_compile plugins/subagent-model-routing-claude/hooks/dag-tripwire.py
python3 -m py_compile plugins/subagent-model-routing-claude/hooks/ledger-tripwire.py
```

The full matrix, including JSON manifest validation and hook pipe tests, lives in `.github/workflows/ci.yml`.

## Conventions

The `SHIM-DONE exit=<n>` contract and the namespaced agent types (`subagent-model-routing-claude:codex-shim`, `subagent-model-routing-claude:opencode-shim`, etc.) are part of the public contract. Changing them requires doc updates across all three packages.

Capability-card rankings and tier lists are seed examples that each user maintains through the `distill` command. PRs that adjust tiers based only on personal experience belong in your own fork's ledger, not here.
