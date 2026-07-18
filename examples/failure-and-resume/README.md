# Failure and resume example

Replace both model identifiers before running. `implement` is a write task and therefore receives an isolated worktree. It retries only a timeout or transport failure, then runs the verification argv without a shell.

```bash
model-routing workflow run workflow.json --host codex
model-routing workflow list
model-routing workflow show <workflow-id>
model-routing workflow resume <workflow-id>
```

The Codex host example intentionally contains no Codex transport task; Codex work stays native in the calling thread. Applying or discarding a successful isolated result remains explicit through `model-routing runs apply|discard <dispatch-id>`.
