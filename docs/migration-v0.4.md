# v0.4 diagnostics and worktree migration

v0.4 is additive. Existing shim names, default shared-directory execution, environment variables, sentinel parsing, ledger paths, JSONL records, and run directories remain compatible with v0.3.

After updating, rerun `scripts/install.sh`. It still validates Python 3.11+ and now finishes with `model-routing doctor --installation-only`. A diagnostic failure does not rewrite authentication, provider configuration, state, or ledger data.

New commands are opt-in:

```bash
model-routing doctor
model-routing runs diff <dispatch-id>
model-routing runs apply <dispatch-id> --target <repo>
model-routing runs discard <dispatch-id> --yes
```

Direct shims continue to run in the shared current directory unless `--routing-workspace isolated` or `auto` is explicit. Isolated worktrees are never applied or removed automatically, and ordinary run cleanup skips them.

Discard revalidates the exact derived path, branch, dispatch owner, live Git worktree entry, and recorded repository common directory. If the repository has moved, discard refuses the operation and preserves the retained worktree for manual recovery.

No database or state migration is required. Existing v0.3 results without workspace artifacts remain readable. The doctor/result schemas are versioned independently at `schemaVersion: 1`.

Live model discovery and the host-neutral workflow scheduler are not part of the historical v0.4 surface; both ship in [v0.5](migration-v0.5.md).
