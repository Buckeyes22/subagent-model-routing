# Isolated worktree dispatch

Isolated mode gives a write-capable routed agent a dedicated Git worktree while leaving the caller's checkout unchanged. It is opt-in and is not a container, sandbox, or credential boundary.

## Dispatch

```bash
codex-shim.sh prompt.md \
  --routing-workspace isolated \
  --routing-task-mode write
```

Workspace modes:

- `shared`: run in the current directory. This remains the compatibility default.
- `isolated`: create an owned branch and worktree for this dispatch.
- `auto`: select shared for `read` and isolated for `write`; it fails unless `--routing-task-mode read|write` is explicit.

An isolated dispatch requires a Git repository and a resolvable base commit. A dirty source worktree is rejected because its uncommitted state cannot be represented safely without guessing. To deliberately exclude those changes and branch from a known commit, pass `--routing-base <commit>`.

The runtime creates:

```text
branch: model-routing/<dispatch-id>
path:   ${STATE_DIR}/worktrees/<dispatch-id>/
```

Repository-scoped locks cover only worktree creation, application, and removal. Provider execution remains concurrent.

## Captured results

After the provider exits—successfully or not—the run retains:

- `workspace.json`: repository identity, base SHA, branch, path, owner, and creation time.
- `changes.patch`: binary patch from the selected base through the final worktree contents, including untracked files.
- `working.patch`: uncommitted changes after the worktree's final commit, used when commits are explicitly replayed.
- `changeset.json`: porcelain status, base/final HEAD, child commits, staged/tracked/untracked/binary paths, manifest, diffstat, and changed-file count.

No child changes are auto-committed, auto-applied, or auto-deleted.

## Review and integration

```bash
model-routing runs diff <dispatch-id>
model-routing runs apply <dispatch-id> --target <repo>
model-routing runs apply <dispatch-id> --target <repo> --commits
model-routing runs discard <dispatch-id>
model-routing runs discard <dispatch-id> --yes
```

Patch application requires a clean target worktree in the recorded Git common directory, rejects unsafe or unmanifested paths, tries direct application before a three-way fallback, and leaves conflicts for the user. `--commits` explicitly cherry-picks captured child commits and then applies any remaining working patch. A cherry-pick conflict deliberately leaves Git's conflict state intact so the user can resolve it and run `git cherry-pick --continue`, or discard it with `git cherry-pick --abort`; the recorded integration message names both recovery commands.

Application never changes the terminal dispatch state. `result.json.integration.status` independently becomes `applied`, `conflicted`, or `discarded` and records the method, identity, and conflict paths.

Discard verifies the dispatch owner, registered branch, and registered worktree path before removal. Without `--yes`, an interactive confirmation is required. `runs cleanup` skips any run whose owned worktree still exists, so accidental retention cleanup cannot destroy reviewable changes.

## Limitations

- Uncommitted source changes are not copied into an isolated worktree.
- Ignored files are not captured as untracked patch content.
- Worktrees share the repository object database and the user's credentials, network, processes, and host permissions.
- Applying generated changes is an explicit trust decision; inspect the patch and rerun project verification afterward.
