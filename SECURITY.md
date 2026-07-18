# Security Policy

## Supported Versions

Only the latest commit on the `main` branch is supported.

## Reporting a Vulnerability

Report vulnerabilities via **GitHub private vulnerability reporting**:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Include a description, reproduction steps, and impact.

Do not open public issues for undisclosed vulnerabilities. Best-effort acknowledgment within 7 days (solo maintainer).

## Scope

The shims intentionally execute AI-directed commands. The default `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1` setting bypasses child-CLI sandbox prompts; this is documented, designed behavior — not a vulnerability.

In-scope: command/argument injection through shim parameters, ledger-write path traversal, hook parsing flaws that could execute content, installer download/verification weaknesses.

Out of scope: risks from the documented opt-in unrestricted execution model; social engineering.

## Optional provider installer boundary

`model-routing setup providers` and interactive bootstrap are explicit mutation surfaces, separate from the read-only doctor and normal shim installation. Missing providers begin unchecked, installed providers are disabled, and selected first-party source domains are shown before a second `[y/N]` confirmation. Automatic bootstrap skips provider setup when `/dev/tty` is unavailable, so CI and redirected installs cannot silently install provider CLIs.

Installer recipes are argv-only data in `config/provider-installers.json`. The loader requires exact provider-registry parity, HTTPS URLs, a fixed `bash`/`sh` interpreter allow-list, and provider-specific redirect hosts. Downloads have connection/read/size bounds, must begin with a shebang, and are written to mode-`0600` temporary files only after validation. Execution uses no `eval`, shell command string, or routing run record; temporary scripts are removed in cleanup paths. One provider failure does not broaden authorization to another provider.

These moving first-party installer URLs do not expose one common detached checksum/signature contract. The checked-in manifest therefore pins the exact reviewed installer bytes with SHA-256 when the endpoint can be inspected. A digest mismatch fails before execution. A provider without a reviewed digest is labeled `WARNING: no pinned checksum` during confirmation and remains protected only by HTTPS, exact origins, redirect allow-listing, bounded content, explicit confirmation, and source review. Upstream installers may perform their own artifact verification and may update user-level PATH configuration. This project never runs provider login commands or writes credentials/provider configuration itself. Users requiring vendor-signed or release-pinned artifacts should use each provider's documented verification flow. See [provider CLI setup](docs/provider-cli-setup.md).

## Runtime data and prompt exposure

The runtime creates private run directories under `${XDG_STATE_HOME:-~/.local/state}/subagent-model-routing/runs/`. Directories are mode `0700`; files are mode `0600`. Prompt bodies are not written by default: `request.json` stores the source type/path, byte length, and SHA-256 digest. `--routing-retain-prompt` explicitly writes `prompt.md`.

Provider stdout and stderr are retained for recovery and can contain source code, credentials printed by tools, or other sensitive material. There is no automatic deletion. Use `model-routing runs cleanup --older-than <days>` or `--all` according to your retention policy. Cleanup skips active isolated worktrees; discard those explicitly after review.

Claude Code, Kimi Code, and Grok Build receive the prompt body as a command-line argument to preserve their verified CLI contracts. While those children run, the prompt may be visible to same-user process inspection tools such as `ps`. Codex and OpenCode receive prompts over stdin. Disabling on-disk prompt retention does not prevent argv visibility. Kimi prompt mode applies its unattended `auto` permission policy while retaining configured static deny rules; `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0` cannot make this CLI mode interactive or manual. The shim rejects `-y`/`--yolo`/`--auto` because Kimi forbids combining them with prompt mode.

Lifecycle hooks are trusted local code configured in `${XDG_CONFIG_HOME:-~/.config}/subagent-model-routing/hooks.json`. Commands execute directly as argument arrays, receive metadata-only event JSON on stdin, and do not receive prompt or output content by default. Hook stdout/stderr is captured privately. Hooks fail open, so malformed configuration must not suppress a shim sentinel.

## Isolated-worktree limitations

`--routing-workspace isolated` protects the caller's checkout from direct edits, but Git worktrees share the repository object database and are not containers. The child retains the same user identity, filesystem permissions, credentials, processes, and network access allowed by its provider sandbox policy. An isolated child can still access paths outside its worktree unless the provider sandbox prevents it.

Dirty source changes are never copied, stashed, or synthesized automatically. Without `--routing-base <commit>`, dirty source repositories are rejected. Ignored files are not included in captured patches.

`runs apply` accepts only an owned run with a safe path manifest, patch paths contained by that manifest, a matching Git common directory, and a clean target worktree. A three-way application can intentionally leave conflicts for manual resolution. Explicit commit replay can leave a cherry-pick in progress; resolve and continue it, or use `git cherry-pick --abort`, as reported by the integration message. Model-generated patches remain untrusted code: inspect `runs diff`, verify the target diff, and rerun project checks before committing. `runs discard` verifies the recorded owner, branch, and worktree path before deletion and requires confirmation unless `--yes` is explicit.

The default doctor is read-only and performs no live model discovery or authentication probe. It may run Kimi's documented `doctor config` validator, which does not modify configuration or validate credential liveness. `--live-auth` opts into documented read-only authentication status commands; Kimi reports `SKIP` because it exposes no such command. `--discover-models` separately opts into bounded provider discovery. OpenCode discovery may contact its configured provider; Codex reads its local CLI cache; Kimi parses only validated model-alias keys from its local provider JSON. Raw output, provider objects, environment values, and credentials are not copied into the doctor report.

## Workflow and nested-orchestration risks

Workflow documents can cause several unattended agents to read, modify, and verify a repository. The scheduler snapshots task prompts and retains selected dependency context, wrapper output, verification output, state, and normal dispatch artifacts below the private workflow/run roots. Treat those files as sensitive and remove them according to the same retention policy as direct runs.

`contextFrom` is deliberately allow-listed and byte-bounded, but selected artifacts may still contain source, secrets printed by tools, or malicious instructions generated by another model. Review workflow files before running them. Verification commands are direct argv arrays without shell expansion, but they are trusted local commands supplied by the workflow author.

The `--host` value is self-declared misuse prevention, not a security boundary. A caller can claim `--host copilot` to pass runner-side native-family validation. Claude's observed-tool tripwire hooks remain the enforcement layer and native Claude Workflow remains the default for Claude-hosted graphs.

Cancellation signals the scheduler and active shim wrappers so provider process groups are terminated. Isolated worktrees are intentionally retained for inspection, including after failure or cancellation. Resume verifies workflow/registry digests, Git repository identity, completed artifacts, and retained write worktrees before scheduling incomplete tasks again.
