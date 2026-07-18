# Public release process

The canonical maintainer source repository is the development source of truth, but its private worktree and history are not the publication boundary. Build every public candidate from that source with the explicit allowlist in `config/public-release-files.json`; never use `git add .` from the private branch and never push its history to the public remote.

## Repository roles

- **Canonical maintainer source:** owns implementation, private design history, release configuration, and the reconciled release state. Run the candidate builder here.
- **Public GitHub history:** contains only reviewed exported files on its own clean history. Base release branches on public `main`.
- **Copies and downstream checkouts:** may be used for review or recovery, but changes made there must be reconciled into the canonical source before a release is built. Never promote a dirty copy by pushing its branch or copying it wholesale over either repository.

The exporter is included in the public tree so contributors and CI can reproduce the boundary, but its presence does not turn a downstream checkout into the maintainer's canonical release source.

## Build the candidate

Choose a new temporary directory outside the repository:

```bash
release_root="$(mktemp -d)"
python3 tools/build_public_release.py "$release_root/candidate"
```

The builder refuses an existing destination, follows no symlinks, copies only approved files, checks known private maintainer markers, and writes `PUBLIC-RELEASE-MANIFEST.json` with the byte size, executable bit, and SHA-256 digest of every source file.

The approved set intentionally excludes private history and planning material such as `PROJECT-CONTEXT.md`, `DESIGN.md`, `PLAN.md`, `review-prompt.md`, `docs/superpowers/`, maintainer audit dossiers, local tool state, and complete third-party system-card copies.

## Validate the exact snapshot

Run checks from the candidate rather than trusting the source worktree:

```bash
cd "$release_root/candidate"
python3 -m pip install --require-hashes --requirement requirements-dev.lock
ruff check runtime tests tools scripts/model-routing
mypy --python-version 3.11 runtime/model_routing tools scripts/model-routing
python3 tools/check_markdown_links.py
python3 tools/validate_json_schemas.py
python3 tools/validate_plugins.py
python3 tools/validate_registry.py
python3 tools/sync_routes.py --check
python3 -m unittest discover -s tests -v
for script in scripts/*.sh; do bash -n "$script"; done
gitleaks dir .
zizmor .github/workflows/ci.yml
```

External scanners are release-machine prerequisites rather than runtime dependencies. Review every scanner finding; do not suppress a real issue merely to obtain a clean report.

## Publish on public history

Create the release branch from the current public `main`, not from the private development branch. Replace the tracked contents only inside a newly created disposable worktree, copy the validated candidate into it, and inspect the complete staged diff before committing. Confirm the worktree path with `git worktree list` before removing or replacing any files.

Required pre-push evidence:

- the staged file list matches `PUBLIC-RELEASE-MANIFEST.json` plus that manifest itself;
- Gitleaks passes both the candidate directory and staged commit;
- no personal email, private remote, machine path, LAN address, credential, or internal-project name appears;
- all plugin versions and the Copilot marketplace entry match the changelog release;
- CI action references use immutable commit SHAs;
- the release tag and README bootstrap command agree.

Push the candidate to a non-default branch first. After its workflow succeeds, require the `checks` status context in branch protection before merging it to `main`. Keep force pushes and branch deletion disabled. Publish release notes from the matching changelog section and verify the tag-pinned bootstrap flow from a disposable user account or machine.

Use this observation-driven GitHub description when updating repository metadata:

> Route Claude Code, Codex, and Copilot work across installed model CLIs with delegation guardrails and an observation-driven routing ledger.
