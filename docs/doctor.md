# Doctor

`model-routing doctor` is a bounded, non-destructive diagnostic for the local routing installation. The default validates the configured runtime and plugin contract without model discovery; discovery is a separate explicit mode.

## Commands

```bash
model-routing doctor
model-routing doctor --json
model-routing doctor --provider codex
model-routing doctor --installation-only
model-routing doctor --provider claude --live-auth
model-routing doctor --discover-models
model-routing doctor --provider opencode --discover-models
model-routing doctor --provider kimi --discover-models
```

The default run inspects local Python and Git availability, state and ledger writability, registry validity, generated assets, installed entrypoints, hook configuration, provider executables and local help/version surfaces, plugin boundaries, version alignment, and security/retention warnings. It also runs `kimi doctor config`, a documented read-only local validation command, when Kimi is selected or installed. Help, version, and configuration commands have bounded timeouts and do not request a provider catalog.

Doctor never installs a provider. Use the separate, explicitly mutating checkbox setup from a terminal when desired:

```bash
model-routing setup providers
model-routing setup providers --dry-run
```

See [optional provider CLI setup](provider-cli-setup.md) for its confirmation, download, and authentication boundaries.

`--installation-only` limits the report to runtime/install checks. The installer uses this mode after creating its symlinks.

`--live-auth` is the only mode allowed to invoke a documented read-only authentication status command. It does not log in, refresh credentials, change configuration, or discover models. Kimi Code currently has no documented read-only authentication-status command—`kimi doctor config` validates configuration rather than credential validity—so Kimi auth reports `SKIP`.

`--discover-models` is the only mode allowed to run model discovery. It reports its command/source in each check: OpenCode runs `opencode models`, Kimi runs the documented `kimi provider list --json` command, Codex reads its CLI-managed local model cache, and Claude/Grok report `SKIP`. Kimi's JSON may contain provider credentials, so discovery parses it in bounded memory and returns only validated keys from the `models` table; raw stdout, stderr, provider objects, environment values, tokens, and credentials are never retained. Missing binaries, timeouts, changed output, malformed caches, and unsupported providers are warnings rather than hard failures.

## Status and exits

Every check is `PASS`, `WARN`, `FAIL`, or `SKIP` and includes remediation when action is appropriate.

- Exit `0`: no `FAIL` checks. Warnings and skips remain visible.
- Exit `1`: one or more environmental failures.
- Exit `2`: invalid invocation, registry, or routing configuration.

JSON output follows [`schemas/doctor-result.schema.json`](../schemas/doctor-result.schema.json), currently `schemaVersion: 1`. Consumers should use check IDs and statuses rather than parsing human summaries.

## Security boundary

Doctor reads local files and may execute `git --version`, a resolved provider binary's local help/version command, and the documented Kimi configuration validator. Default operation does not write probe files, authenticate, update CLIs, contact model catalogs, or rewrite provider configuration. Explicit discovery may contact a provider if its CLI's own list implementation does so; Kimi's configured-provider listing is local, while OpenCode controls the behavior of `opencode models`. Discovery never runs during install checks or dispatch preflight. Use a restricted environment or provider-specific offline controls if an installed CLI behaves unexpectedly.
