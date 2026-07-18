# Contributing

Issues and pull requests are welcome.

## Local checks

Run the same checks CI runs before pushing:

```bash
python3 -m pip install --require-hashes --requirement requirements-dev.lock
git diff --check
ruff check runtime tests tools scripts/model-routing
mypy --python-version 3.11 runtime/model_routing tools scripts/model-routing
python3 tools/check_markdown_links.py
python3 tools/validate_json_schemas.py
python3 tools/validate_plugins.py
python3 tools/check_generated.py
actionlint
for s in scripts/*.sh; do bash -n "$s"; done
python3 -m compileall -q runtime tests tools scripts/model-routing
python3 -m unittest discover -s tests -v
python3 tools/validate_registry.py
python3 tools/sync_routes.py --check
python3 scripts/model-routing doctor --json >/dev/null
[ "$(bash scripts/codex-shim.sh 2>&1 | tail -1)" = "SHIM-DONE exit=64" ]
[ "$(bash scripts/opencode-shim.sh 2>&1 | tail -1)" = "SHIM-DONE exit=64" ]
[ "$(bash scripts/grok-shim.sh 2>&1 | tail -1)" = "SHIM-DONE exit=64" ]
[ "$(bash scripts/claude-shim.sh 2>&1 | tail -1)" = "SHIM-DONE exit=64" ]
[ "$(bash scripts/kimi-shim.sh 2>&1 | tail -1)" = "SHIM-DONE exit=64" ]
python3 -m py_compile plugins/subagent-model-routing-claude/hooks/dag-tripwire.py
python3 -m py_compile plugins/subagent-model-routing-claude/hooks/ledger-tripwire.py
```

The full matrix, including JSON manifest validation and hook pipe tests, lives in `.github/workflows/ci.yml`. CI also builds the explicit allowlist in `config/public-release-files.json` and reruns the complete suite inside that privacy-checked snapshot; see `docs/releasing.md` before preparing a public release.

Python 3.11 is the runtime floor. CI also exercises 3.12 and 3.13; runtime code must remain standard-library-only.

Doctor tests must use temporary homes, fake executables, or subprocess mocks and must prove the default path performs no authentication or model-discovery probe. Explicit-discovery tests must bound output and prove raw output/secrets are not retained. Worktree and scheduler tests must create disposable Git repositories below `tempfile.TemporaryDirectory()`; never point them at the contributor's checkout. Cover binary/untracked paths, dirty-source refusal, apply conflicts, ownership checks, terminal-state preservation, dependency ordering, concurrency, retry classification, cancellation, verification argv, and resume invariants.

Workflow schema changes must update `schemas/workflow.schema.json`, semantic validation in `runtime/model_routing/workflow.py`, scheduler tests, both workflow examples, all three host-specific skills, and `docs/workflows.md` together. Workflow tests use fake providers; CI must never spend provider quota or depend on network access.

## Conventions

The `SHIM-DONE exit=<n>` contract and the namespaced Claude-package agent types (`subagent-model-routing-claude:codex-shim`, `subagent-model-routing-claude:kimi-shim`, `subagent-model-routing-claude:opencode-shim`, `subagent-model-routing-claude:grok-shim`, etc.) are part of the public contract. The direct-shell packages also expose `claude-shim`; changing a route requires updating only the client packages that actually support it.

Capability-card rankings and tier lists are seed examples that each user maintains through the `distill` command. PRs that adjust tiers based only on personal experience belong in your own fork's ledger, not here.

This project may adopt ideas and behavior observed elsewhere, but do not copy Devchain source or ELv2-licensed text into the repository. Provider-registry changes must regenerate all host views with `python3 tools/sync_routes.py`; update shared runtime/reference material and only the client packages that expose the changed route.
