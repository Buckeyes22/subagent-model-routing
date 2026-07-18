# Lifecycle hook example

Copy [`../lifecycle-hooks.json`](../lifecycle-hooks.json) to `${XDG_CONFIG_HOME:-~/.config}/subagent-model-routing/hooks.json` and replace its command with a trusted local executable.

Hook commands receive metadata-only event JSON on stdin. They do not receive the prompt or provider output by default, execute with bounded timeouts, fail open, and write their stdout/stderr only to the run's private hook artifacts.
