# Optional provider CLI setup

`model-routing setup providers` is an explicit, dependency-free checkbox installer for the five optional CLI harnesses used by the transport shims: Codex, Claude Code, Grok Build, Kimi Code, and OpenCode. The provider executables are not bundled with this repository.

## Bootstrap behavior

An interactive `scripts/bootstrap.sh` run installs the shared runtime first, then opens the provider selector when `/dev/tty` is available. This also works for the documented `curl | bash` command because selection input is read directly from `/dev/tty`, never from the pipe carrying the bootstrap script.

Missing providers begin unchecked. Installed providers are shown as `[x]`, include their resolved path, and cannot be selected for reinstall or upgrade.

Controls:

- Up/Down or `k`/`j`: move between missing providers
- Space: toggle the highlighted provider
- Enter: continue; if nothing is selected, skip
- `q` or Escape: skip without installing anything
- Ctrl-C: restore the terminal and stop with exit 130

The selector shows the exact source domains and whether each installer has a reviewed SHA-256 digest, then asks for a second `[y/N]` confirmation before downloading anything. An unpinned source is labeled with an explicit warning. The default answer is no.

Use bootstrap flags to control it:

```bash
# Require the checkbox screen; fail if no controlling terminal is available.
scripts/bootstrap.sh --provider-menu

# Install only the router/shims and skip provider setup.
scripts/bootstrap.sh --no-provider-menu

# Provider setup remains compatible with client plugin registration.
scripts/bootstrap.sh --provider-menu --register
```

In CI, cron, redirected sessions, or any process without `/dev/tty`, automatic mode skips provider setup and prints the manual command. It never waits on stdin and never installs a provider noninteractively. Automatic mode also skips when `TERM=dumb`; manual `--no-color` mode remains available.

## Run or rerun it manually

After the shared installer has linked `model-routing`:

```bash
~/.claude/scripts/model-routing setup providers
~/.claude/scripts/model-routing setup providers --dry-run
~/.claude/scripts/model-routing setup providers --no-color
```

`--dry-run` opens the same selector and confirmation, then prints the manifest-defined URL and interpreter without downloading or executing anything. Re-running normal setup is the recovery path after a partial failure: successfully installed CLIs are detected and disabled, leaving only missing providers selectable.

## Supported platforms

The Bash bootstrap and checkbox selector support:

- macOS
- Linux
- Windows through WSL (treated as Linux)

Native PowerShell and Command Prompt installer orchestration are not included. Install provider CLIs from their first-party Windows documentation instead, then use this project from its supported shell environment.

Provider setup does not install Git, Python, Node.js, Homebrew, GNU `timeout`, WSL, or a system package manager. Python 3.11+, Git, and GNU `timeout`/`gtimeout` remain separately diagnosed runtime prerequisites.

## Installer sources

`config/provider-installers.json` is the declarative source of truth. Display names, executable resolution, and override environment variables continue to come from `config/provider-registry.json`; the two registries must have exactly the same provider IDs.

The installer sources were re-verified against first-party documentation on 2026-07-17:

| Provider | Installer URL | Checksum status | First-party documentation |
|---|---|---|---|
| Codex | `https://chatgpt.com/codex/install.sh` | reviewed SHA-256 pinned | [OpenAI Codex](https://github.com/openai/codex) |
| Claude Code | `https://claude.ai/install.sh` | reviewed SHA-256 pinned | [Claude Code setup](https://code.claude.com/docs/en/getting-started) |
| Grok Build | `https://x.ai/cli/install.sh` | reviewed SHA-256 pinned | [Grok Build overview](https://docs.x.ai/build/overview) |
| Kimi Code | `https://code.kimi.com/kimi-code/install.sh` | unavailable from the verification network; explicit warning | [Kimi Code setup](https://moonshotai.github.io/kimi-code/en/guides/getting-started.html) |
| OpenCode | `https://opencode.ai/install` | reviewed SHA-256 pinned | [OpenCode setup](https://opencode.ai/docs/) |

The runtime does not use npm as a universal fallback. If a first-party standalone installer is unavailable or changes its redirect target, setup fails with the documentation link rather than guessing another package-manager command.

Static source review on the verification date observed these delivery details without executing the scripts on the maintainer account:

| Provider | Observed delivery behavior |
|---|---|
| Codex | POSIX `sh`; about 25 KiB; redirects through `github.com` to `release-assets.githubusercontent.com`; installs a user-level binary under `~/.local/bin` and verifies the downloaded release artifact |
| Claude Code | Bash; about 6 KiB; redirects to `downloads.claude.ai`; keeps native-install data under `~/.claude` |
| Grok Build | Bash; about 17 KiB; remains on `x.ai`; uses the user-level `~/.grok/bin` location |
| Kimi Code | The exact Bash installer URL is present in MoonshotAI's current repository and guide. The endpoint was not reachable from the release-review network, so its response and any redirect could not be independently inspected there; setup permits only `code.kimi.com` and fails closed if delivery differs. |
| OpenCode | Bash; about 14 KiB; redirects to `raw.githubusercontent.com`; uses the user-level `~/.opencode/bin` location |

The Linux flow was additionally exercised with Codex in a disposable clean HOME: the selector and confirmation installed only Codex, the binary became discoverable on the refreshed user PATH, its local version check succeeded, and doctor reported `provider.codex.binary_resolved` as passing. No live recipe was run over an existing maintainer installation. Portable provider-setup and bootstrap tests also run in the macOS CI smoke job; WSL follows the tested Linux manifest and runtime path.

When updating a recipe:

1. Re-check the current first-party documentation.
2. Download the installer without executing it and inspect its redirect chain, interpreter, size, and user-level install path.
3. Record the reviewed response's SHA-256 digest, or use `null` only when the endpoint cannot be inspected and document why.
4. Update the URL/redirect allow-list and `sourceVerifiedOn` date.
5. Run the schema, semantic, offline setup, PTY, and bootstrap tests.
6. Validate the real installer only in a disposable VM, container, or dedicated clean user—not over an active maintainer installation.

## Security boundary

Selecting a provider authorizes this tool to download and execute that provider's manifest-defined installer. It does not authorize any other provider, an upgrade of an already resolved binary, authentication, model discovery, API-key entry, or provider configuration by this project.

Before execution, setup:

- accepts only fixed HTTPS URLs from the checked-in manifest;
- rejects every redirect hop whose HTTPS hostname is absent from the provider-specific allow-list, then revalidates the final URL;
- bounds connection/read time and installer size;
- requires a non-empty script beginning with a shebang;
- compares the response with the manifest's reviewed SHA-256 digest when present and aborts on mismatch;
- downloads into memory, then writes a mode-`0600` temporary file;
- executes a fixed `bash` or `sh` argv array with no shell interpolation or `eval`;
- streams installer output directly to the user's terminal without adding it to routing run records; and
- removes the temporary script after success, failure, timeout, or interruption.

The manifest digest proves that a download matches the exact bytes reviewed by this project's maintainer; it is not a vendor signature and does not establish who authored those bytes. Some upstream installers verify the artifacts they subsequently download. An unavailable digest is shown as a warning and relies on fixed HTTPS origins, redirect allow-listing, bounded downloads, explicit confirmation, and first-party recipe review. Users who require vendor-authenticated artifacts should follow the provider's documented release/signature process directly.

Official installers may create user-level directories and update shell PATH configuration according to their own documented behavior. This project does not edit shell profiles itself. After setup, the current bootstrap process temporarily adds existing common user binary directories to PATH so a newly installed Claude or Codex host can be registered in the same run.

No login command is executed. Authenticate afterward as applicable:

```bash
codex login
claude auth login
grok login                  # or configure XAI_API_KEY for headless use
kimi login
opencode auth login
```

## Results and recovery

Selected providers run independently in stable registry order. A failed provider does not prevent later selections from running. The final summary distinguishes download errors, installer nonzero exits/timeouts, unresolved binaries, and failed local version checks.

Exit codes:

- `0`: all selected installs verified, all providers were already installed, nothing was selected, confirmation was declined, or setup was skipped
- `1`: at least one selected provider failed to download, install, resolve, or verify
- `2`: invalid manifest/invocation, unsupported native platform, or required TTY unavailable
- `130`: Ctrl-C

Bootstrap continues to print registration and recovery guidance after optional setup exit 1, then returns nonzero so the failure is visible. An explicitly forced menu propagates invocation errors immediately.

After resolving a failure:

```bash
~/.claude/scripts/model-routing setup providers
~/.claude/scripts/model-routing doctor
```

The default doctor remains read-only and does not install, authenticate, upgrade, or discover models.
