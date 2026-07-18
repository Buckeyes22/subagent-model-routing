# Lifecycle hooks

Portable runtime hooks are configured in:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/subagent-model-routing/hooks.json
```

Example:

```json
{
  "dispatch.failed": [
    {
      "command": ["/home/user/bin/notify-routing-failure"],
      "timeoutSeconds": 5,
      "failurePolicy": "ignore"
    }
  ]
}
```

Commands are argument arrays, never shell strings. Each hook receives the lifecycle event JSON on stdin and minimal metadata through:

- `SUBAGENT_MODEL_ROUTING_EVENT`
- `SUBAGENT_MODEL_ROUTING_DISPATCH_ID`
- `SUBAGENT_MODEL_ROUTING_PROVIDER`
- `SUBAGENT_MODEL_ROUTING_MODEL`
- `SUBAGENT_MODEL_ROUTING_WORKFLOW_ID` (workflow attempts only)
- `SUBAGENT_MODEL_ROUTING_TASK_ID` (workflow attempts only)
- `SUBAGENT_MODEL_ROUTING_HOOK_DEPTH`

Prompt and provider output contents are not included. Hook stdout/stderr and status are captured below the run's `hooks/` directory and never mixed with shim streams.

## Failure policy

v0.3 hooks are fail-open. Invalid JSON, malformed definitions, missing commands, timeouts, nonzero exits, invalid recursion-depth values, and hook-artifact failures do not change the provider exit or suppress the final sentinel. `failurePolicy` is reserved for compatibility; completion events do not support fail-closed behavior in this release.

Recursive routing is bounded by the hook-depth environment value. A malformed external value is treated as depth zero, while a depth of three or greater prevents further hook execution.

These hooks do not replace Claude Code's package-specific Stop hooks. Claude's ledger and DAG tripwires remain the host enforcement/advisory layer; runtime hooks are portable local automation.
