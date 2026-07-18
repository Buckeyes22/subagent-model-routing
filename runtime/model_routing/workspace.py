"""Shared, isolated, and auto workspace resolution with isolated Git worktree management."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable, Mapping
import uuid

from .run_store import FILE_MODE, RunStore, atomic_write_bytes, atomic_write_json, ensure_private_directory, state_root, utc_now


WORKSPACE_SCHEMA_VERSION = 1
CHANGESET_SCHEMA_VERSION = 1
INTEGRATION_SCHEMA_VERSION = 1

WORKSPACE_MODES = ("shared", "isolated", "auto")
TASK_MODES = ("read", "write")
INTEGRATION_STATUSES = ("not_applied", "applied", "conflicted", "discarded")
TERMINAL_DISPATCH_STATUSES = {"succeeded", "failed", "timed_out", "cancelled", "preflight_failed"}


class WorkspaceError(RuntimeError):
    """Base class for workspace-level failures."""


class UsageConfigurationError(WorkspaceError):
    """The workspace request is invalid or insufficiently specified."""


class DirtySourceError(WorkspaceError):
    """The source worktree is dirty and no explicit base ref was supplied."""


class BranchCollisionError(WorkspaceError):
    """An isolated branch already exists for this dispatch."""


class NotAGitRepositoryError(WorkspaceError):
    """The supplied path is not inside a Git repository."""


class OwnershipError(WorkspaceError):
    """The worktree does not belong to the supplied dispatch."""


class DirtyTargetError(WorkspaceError):
    """The target repository is not clean for apply."""


class RepositoryMismatchError(WorkspaceError):
    """The target repository does not match the recorded common dir."""


class GitCommandError(WorkspaceError):
    """An invocation of Git returned a non-zero exit code."""


@dataclass(slots=True)
class WorkspaceRequest:
    mode: str
    task_mode: str | None = None


@dataclass(slots=True)
class WorktreeMetadata:
    schemaVersion: int
    dispatchId: str
    ownerDispatchId: str
    repositoryCommonDir: str
    sourceWorktree: str
    baseRef: str | None
    baseSha: str
    branch: str
    path: str
    createdAt: str
    cleanupEligible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Changeset:
    schemaVersion: int
    dispatchId: str
    worktreePath: str
    baseRef: str | None
    baseSha: str
    finalSha: str
    capturedAt: str
    statusPorcelainV2: str
    commits: list[dict[str, str]]
    stagedPaths: list[str]
    trackedPaths: list[str]
    untrackedPaths: list[str]
    binaryPaths: list[str]
    manifest: list[dict[str, Any]]
    diffstat: str
    numstat: str
    changedFileCount: int
    patchPath: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ApplyOutcome:
    status: str
    appliedAt: str
    target: str
    appliedCommits: list[str]
    conflictedFiles: list[str]
    method: str
    identity: str | None
    message: str | None = None


def worktree_root(env: Mapping[str, str]) -> Path:
    """Return the absolute worktree storage directory under the state root."""
    return state_root(env) / "worktrees"


def worktree_path(env: Mapping[str, str], dispatch_id: str) -> Path:
    _validate_dispatch_id(dispatch_id)
    return worktree_root(env) / dispatch_id


def _validate_dispatch_id(dispatch_id: str) -> None:
    if not isinstance(dispatch_id, str) or not dispatch_id:
        raise UsageConfigurationError("dispatch id must be a non-empty string")
    try:
        parsed = uuid.UUID(dispatch_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise UsageConfigurationError(f"invalid dispatch id: {dispatch_id!r}") from exc
    if str(parsed) != dispatch_id:
        raise UsageConfigurationError(f"dispatch id must be canonical UUID: {dispatch_id!r}")


def resolve_workspace(request: WorkspaceRequest | Mapping[str, Any]) -> str:
    """Resolve ``shared``/``isolated``/``auto`` to a concrete workspace mode.

    Auto requires an explicit ``task_mode`` of ``read`` or ``write``; read
    resolves to ``shared`` and write resolves to ``isolated``. Anything else
    is rejected so callers cannot accidentally launch an isolated dispatch
    for a read-only task or vice versa.
    """
    if isinstance(request, WorkspaceRequest):
        raw_mode: Any = request.mode
        task_mode = request.task_mode
    elif isinstance(request, Mapping):
        raw_mode = request.get("mode")
        task_mode = request.get("task_mode")
    else:
        raise UsageConfigurationError("workspace request must be a mapping or WorkspaceRequest")

    if not isinstance(raw_mode, str) or raw_mode not in WORKSPACE_MODES:
        raise UsageConfigurationError(
            f"workspace mode must be one of {', '.join(WORKSPACE_MODES)}; got {raw_mode!r}"
        )
    mode = raw_mode
    if mode != "auto":
        return mode
    if task_mode not in TASK_MODES:
        raise UsageConfigurationError(
            "workspace mode 'auto' requires --routing-task-mode read|write; "
            f"got task_mode={task_mode!r}"
        )
    return "shared" if task_mode == "read" else "isolated"


def _run_git(argv: list[str], *, cwd: Path, env: Mapping[str, str] | None = None,
             input_bytes: bytes | None = None, check: bool = True,
             capture: bool = True) -> subprocess.CompletedProcess[bytes]:
    full_env = dict(os.environ if env is None else env)
    full_env.setdefault("LC_ALL", "C.UTF-8")
    full_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        return subprocess.run(
            ["git", *argv],
            cwd=str(cwd),
            env=full_env,
            input=input_bytes,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            check=check,
        )
    except FileNotFoundError as exc:
        raise GitCommandError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise GitCommandError(f"git {' '.join(argv)} failed: {stderr}") from exc


def _canonical(path: Path) -> str:
    return str(path.resolve())


def _ensure_inside_repo(cwd: Path, repo_common_dir: str) -> Path:
    common = Path(repo_common_dir).resolve()
    target = cwd.resolve()
    try:
        target.relative_to(common)
    except ValueError as exc:
        raise NotAGitRepositoryError(f"{cwd} is not inside repository {common}") from exc
    return target


def _repository_common_dir(cwd: Path) -> tuple[Path, Path]:
    """Return ``(common_dir, work_tree)`` for ``cwd``; raise if not a repo."""
    try:
        result = _run_git(["rev-parse", "--git-common-dir", "--show-toplevel"], cwd=cwd)
    except GitCommandError as exc:
        raise NotAGitRepositoryError(f"{cwd} is not inside a Git repository: {exc}") from exc
    parts = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise NotAGitRepositoryError(f"git rev-parse returned unexpected output for {cwd}")
    common_value = Path(parts[0])
    common = (Path(parts[1]) / common_value).resolve() if not common_value.is_absolute() else common_value.resolve()
    work_tree = Path(parts[1]).resolve()
    if not (common / "HEAD").exists() and not (common / "config").exists():
        raise NotAGitRepositoryError(f"{common} does not look like a Git common directory")
    return common, work_tree


def _repo_lock_path(state_dir: Path, common_dir: Path) -> Path:
    fingerprint = hashlib.sha256(_canonical(common_dir).encode("utf-8")).hexdigest()[:16]
    return state_dir / "locks" / f"{fingerprint}.lock"


class RepositoryLock:
    """Repository-scoped advisory lock for create/apply/discard operations.

    A single shared lock covers every worktree that targets the same source
    repository, so concurrent isolated dispatches against one repo are
    serialized. The lock is non-blocking on the same process and reentrant.
    """

    _depth_key = "_model_routing_repo_lock_depth"

    def __init__(self, env: Mapping[str, str], repo_common_dir: Path) -> None:
        self.env = dict(env)
        self.repo_common_dir = Path(repo_common_dir).resolve()
        self.lock_path = _repo_lock_path(state_root(self.env), self.repo_common_dir)
        self._fd: int | None = None

    def acquire(self) -> None:
        ensure_private_directory(self.lock_path.parent)
        depth = self.env.get(self._depth_key)
        if depth and int(depth) > 0:
            self.env[self._depth_key] = str(int(depth) + 1)
            return
        fd = os.open(str(self.lock_path), os.O_WRONLY | os.O_CREAT, FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            os.close(fd)
            raise
        self._fd = fd
        self.env[self._depth_key] = "1"

    def release(self) -> None:
        depth = int(self.env.get(self._depth_key, "0") or "0")
        if depth <= 1:
            if self._fd is not None:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                finally:
                    os.close(self._fd)
                self._fd = None
                self.env.pop(self._depth_key, None)
        elif depth > 1:
            self.env[self._depth_key] = str(depth - 1)

    def __enter__(self) -> "RepositoryLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


def _status_is_clean(work_tree: Path) -> bool:
    result = _run_git(["status", "--porcelain=v2", "--untracked-files=all", "-z"], cwd=work_tree)
    return len(result.stdout) == 0


def _list_worktrees(common_dir: Path) -> list[dict[str, str]]:
    result = _run_git(["worktree", "list", "--porcelain"], cwd=common_dir)
    text = result.stdout.decode("utf-8", errors="replace")
    entries: list[dict[str, str]] = []
    for chunk in text.split("\n\n"):
        if not chunk.strip():
            continue
        entry: dict[str, str] = {}
        for line in chunk.splitlines():
            key, _, value = line.partition(" ")
            entry[key] = value
        entries.append(entry)
    return entries


def _branch_exists(common_dir: Path, branch: str) -> bool:
    result = _run_git(["show-ref", "--verify", f"refs/heads/{branch}"], cwd=common_dir, check=False)
    return result.returncode == 0


def _worktree_path_for_branch(common_dir: Path, branch: str) -> Path | None:
    expected = f"refs/heads/{branch}"
    for entry in _list_worktrees(common_dir):
        if entry.get("branch") == expected and entry.get("worktree"):
            return Path(entry["worktree"]).resolve()
    return None


def _resolve_base_ref(cwd: Path, base_ref: str | None) -> str:
    """Resolve a base ref or sha into a 40-char hex sha; raise on failure."""
    requested = base_ref or "HEAD"
    try:
        result = _run_git(["rev-parse", "--verify", f"{requested}^{{commit}}"], cwd=cwd)
    except GitCommandError as exc:
        raise UsageConfigurationError(f"cannot resolve base ref {requested!r}: {exc}") from exc
    sha = result.stdout.decode("utf-8", errors="replace").strip()
    if not re_fullmatch_hex(sha):
        raise UsageConfigurationError(f"base ref {requested!r} did not resolve to a commit sha")
    return sha


def re_fullmatch_hex(value: str) -> bool:
    return len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def prepare_isolated_worktree(
    env: Mapping[str, str],
    dispatch_id: str,
    source_path: Path,
    *,
    base_ref: str | None = None,
) -> WorktreeMetadata:
    """Prepare an isolated Git worktree under ``STATE_DIR/worktrees/<dispatch-id>``.

    Refuses to operate when the source worktree is dirty unless ``base_ref``
    is supplied. Writes a ``workspace.json`` ownership record that later
    ``apply`` and ``discard`` calls rely on to reject foreign worktrees.
    """
    _validate_dispatch_id(dispatch_id)
    source = Path(source_path).resolve()
    common_dir, source_worktree = _repository_common_dir(source)

    state_dir = state_root(env)
    ensure_private_directory(state_dir)

    branch = f"model-routing/{dispatch_id}"
    wt_path = worktree_path(env, dispatch_id)

    with RepositoryLock(env, common_dir):
        existing_branch = _branch_exists(common_dir, branch)
        if existing_branch:
            existing_wt = _worktree_path_for_branch(common_dir, branch)
            metadata_path = _run_store(env, dispatch_id).artifact("workspace.json")
            if existing_wt is not None and existing_wt == wt_path:
                # Idempotent retry for the same dispatch: return the existing
                # ownership record if it still matches.
                if metadata_path.is_file():
                    metadata = _load_workspace_metadata(metadata_path)
                    if metadata.ownerDispatchId == dispatch_id:
                        return metadata
            raise BranchCollisionError(
                f"branch {branch!r} already exists for this dispatch; "
                "discard the existing worktree before creating a new one"
            )

        is_clean = _status_is_clean(source_worktree)
        if not is_clean and not base_ref:
            raise DirtySourceError(
                "source worktree is dirty; pass --routing-base <commit> or commit, "
                "stash, or use --routing-workspace shared"
            )

        base_sha = _resolve_base_ref(source_worktree, base_ref)

        # The worktree directory must not exist before `git worktree add`.
        if wt_path.exists():
            raise WorkspaceError(
                f"worktree path {wt_path} already exists; refuse to overwrite "
                "an unrecognized worktree"
            )
        ensure_private_directory(state_dir / "worktrees")

        try:
            _run_git(
                ["worktree", "add", "-b", branch, str(wt_path), base_sha],
                cwd=common_dir,
            )
        except GitCommandError:
            raise

        metadata = WorktreeMetadata(
            schemaVersion=WORKSPACE_SCHEMA_VERSION,
            dispatchId=dispatch_id,
            ownerDispatchId=dispatch_id,
            repositoryCommonDir=_canonical(common_dir),
            sourceWorktree=_canonical(source_worktree),
            baseRef=base_ref,
            baseSha=base_sha,
            branch=branch,
            path=_canonical(wt_path),
            createdAt=utc_now(),
            cleanupEligible=True,
        )
        try:
            atomic_write_json(_run_store(env, dispatch_id).artifact("workspace.json"), metadata.to_dict())
        except OSError:
            _safe_remove_worktree(common_dir, wt_path, branch, dispatch_id)
            raise

    return metadata


def _safe_remove_worktree(common_dir: Path, wt_path: Path, branch: str, dispatch_id: str) -> None:
    """Best-effort cleanup used only on internal failure paths."""
    try:
        _run_git(["worktree", "remove", "--force", str(wt_path)], cwd=common_dir, check=False)
    except GitCommandError:
        pass
    try:
        _run_git(["worktree", "prune"], cwd=common_dir, check=False)
    except GitCommandError:
        pass
    try:
        _run_git(["branch", "-D", branch], cwd=common_dir, check=False)
    except GitCommandError:
        pass
    if wt_path.exists():
        shutil.rmtree(wt_path, ignore_errors=True)


def _load_workspace_metadata(path: Path) -> WorktreeMetadata:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OwnershipError(f"workspace.json is unreadable or corrupt: {exc}") from exc
    if not isinstance(raw, dict):
        raise OwnershipError("workspace.json is not an object")
    try:
        return WorktreeMetadata(
            schemaVersion=int(raw["schemaVersion"]),
            dispatchId=str(raw["dispatchId"]),
            ownerDispatchId=str(raw["ownerDispatchId"]),
            repositoryCommonDir=str(raw["repositoryCommonDir"]),
            sourceWorktree=str(raw["sourceWorktree"]),
            baseRef=raw.get("baseRef"),
            baseSha=str(raw["baseSha"]),
            branch=str(raw["branch"]),
            path=str(raw["path"]),
            createdAt=str(raw["createdAt"]),
            cleanupEligible=bool(raw.get("cleanupEligible", True)),
        )
    except (KeyError, TypeError) as exc:
        raise OwnershipError(f"workspace.json is missing required fields: {exc}") from exc


def _run_store(env: Mapping[str, str], dispatch_id: str) -> RunStore:
    return RunStore.create(env, dispatch_id)


def _split_porcelain_v2(data: bytes) -> list[dict[str, Any]]:
    """Parse ``git status --porcelain=v2 -z`` output.

    The ``-z`` form NUL-delimits records. Untracked records are a single
    line beginning with ``?`` followed by the path. Changed records carry
    8 fixed fields followed by the path. We avoid pulling in a third-party
    parser and rely on documented layout.
    """
    if not data:
        return []
    records: list[dict[str, Any]] = []
    for chunk in data.split(b"\x00"):
        if not chunk:
            continue
        text = chunk.decode("utf-8", errors="replace")
        if text.startswith("? "):
            records.append({"kind": "untracked", "path": text[2:]})
            continue
        if text.startswith("1 ") or text.startswith("2 "):
            parts = text.split(" ")
            # 1/2 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>
            if len(parts) >= 9:
                records.append(
                    {
                        "kind": "changed",
                        "path": parts[8],
                        "code": parts[1],
                        "stagedXY": parts[1][0],
                        "unstagedXY": parts[1][1],
                    }
                )
        elif text.startswith("u "):
            parts = text.split(" ")
            if len(parts) >= 3:
                records.append({"kind": "unmerged", "path": " ".join(parts[2:])})
    return records


def _classify_paths(records: Iterable[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    staged: list[str] = []
    tracked: list[str] = []
    untracked: list[str] = []
    for record in records:
        kind = record["kind"]
        if kind == "untracked":
            untracked.append(record["path"])
            continue
        if kind == "changed":
            if record["stagedXY"] != ".":
                staged.append(record["path"])
            if record["unstagedXY"] != ".":
                tracked.append(record["path"])
        elif kind == "unmerged":
            staged.append(record["path"])
    return staged, tracked, untracked


def _detect_binary_files(work_tree: Path, paths: Iterable[str]) -> list[str]:
    binary: list[str] = []
    for relpath in paths:
        target = work_tree / relpath
        if not target.exists() or target.is_dir():
            continue
        try:
            with target.open("rb") as handle:
                chunk = handle.read(8192)
        except OSError:
            continue
        if b"\x00" in chunk:
            binary.append(relpath)
    return binary


def _nul_paths(payload: bytes) -> list[str]:
    return [item.decode("utf-8", errors="surrogateescape") for item in payload.split(b"\0") if item]


def _capture_snapshot(
    work_tree: Path,
    base_sha: str,
    index_path: Path,
) -> tuple[bytes, str, str, list[str], list[dict[str, Any]]]:
    """Build a binary patch from ``base_sha`` without changing the real index."""
    try:
        index_path.unlink()
    except FileNotFoundError:
        pass
    capture_env = dict(os.environ)
    capture_env["GIT_INDEX_FILE"] = str(index_path)
    try:
        _run_git(["read-tree", base_sha], cwd=work_tree, env=capture_env)
        _run_git(["add", "-A", "--", "."], cwd=work_tree, env=capture_env)
        patch = _run_git(
            ["diff", "--cached", "--binary", "--no-renames", "--no-color", "--no-ext-diff", base_sha],
            cwd=work_tree,
            env=capture_env,
        ).stdout
        names = _nul_paths(
            _run_git(["diff", "--cached", "--name-only", "--no-renames", "-z", base_sha], cwd=work_tree, env=capture_env).stdout
        )
        numstat = _run_git(
            ["diff", "--cached", "--numstat", "--no-renames", base_sha], cwd=work_tree, env=capture_env
        ).stdout.decode("utf-8", errors="replace")
        shortstat = _run_git(
            ["diff", "--cached", "--shortstat", base_sha], cwd=work_tree, env=capture_env
        ).stdout.decode("utf-8", errors="replace").strip()
    finally:
        try:
            index_path.unlink()
        except FileNotFoundError:
            pass

    rows_by_path: dict[str, dict[str, Any]] = {}
    for line in numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            added, removed, path = parts
            rows_by_path[path] = {
                "path": path,
                "added": added,
                "removed": removed,
                "binary": added == "-" or removed == "-",
            }
    manifest = []
    for path in names:
        row = rows_by_path.get(path, {"path": path, "added": "0", "removed": "0", "binary": False})
        row["mode"] = "binary" if row["binary"] else "text"
        manifest.append(row)
    return patch, numstat, shortstat, names, manifest


def _format_diffstat(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    max_width = max(len(row["path"]) for row in rows)
    lines: list[str] = []
    for row in rows:
        if row["binary"]:
            size_field = f"{row['added']} -> {row['removed']} bytes"
            marker = " | Bin "
        else:
            size_field = f"{row['added']} +-{row['removed']}"
            marker = " | "
        lines.append(f" {row['path'].ljust(max_width)}{marker}{size_field}")
    return "\n".join(lines)


def capture_changes(
    env: Mapping[str, str],
    dispatch_id: str,
    *,
    metadata: WorktreeMetadata | None = None,
) -> Changeset:
    """Capture terminal changes in an isolated worktree without auto-committing.

    Writes ``changes.patch`` and ``changeset.json`` under the dispatch run
    directory, plus an integration record stamped ``not_applied`` if the
    dispatch has already produced ``result.json``. Does not modify the
    terminal dispatch status.
    """
    _validate_dispatch_id(dispatch_id)
    if metadata is None:
        metadata = load_worktree_metadata(env, dispatch_id)
    wt_path = Path(metadata.path)
    if not wt_path.exists():
        raise WorkspaceError(f"isolated worktree {wt_path} no longer exists")

    with RepositoryLock(env, Path(metadata.repositoryCommonDir)):
        base_sha = metadata.baseSha
        final_sha = _run_git(["rev-parse", "HEAD"], cwd=wt_path).stdout.decode("utf-8").strip()

        status_result = _run_git(
            ["status", "--porcelain=v2", "--untracked-files=all", "-z"], cwd=wt_path
        )
        status_text = status_result.stdout.decode("utf-8", errors="replace")

        store = _run_store(env, dispatch_id)
        staged = _nul_paths(_run_git(["diff", "--cached", "--name-only", "-z", base_sha], cwd=wt_path).stdout)
        tracked = _nul_paths(_run_git(["diff", "--name-only", "-z", base_sha], cwd=wt_path).stdout)
        untracked = _nul_paths(_run_git(["ls-files", "--others", "--exclude-standard", "-z"], cwd=wt_path).stdout)
        diff, numstat_text, shortstat, changed_paths, manifest = _capture_snapshot(
            wt_path, base_sha, store.artifact("capture.index")
        )
        working_diff, _, _, _, _ = _capture_snapshot(
            wt_path, final_sha, store.artifact("working-capture.index")
        )
        binary = sorted(row["path"] for row in manifest if row["binary"])
        commits = _list_commits(base_sha, final_sha, wt_path)

        patch_path = store.artifact("changes.patch")
        atomic_write_bytes(patch_path, diff)
        atomic_write_bytes(store.artifact("working.patch"), working_diff)
        ensure_private_directory(patch_path.parent)

        untracked_record_path = store.artifact("untracked-files.json")
        atomic_write_json(
            untracked_record_path,
            {"schemaVersion": 1, "dispatchId": dispatch_id, "paths": untracked},
        )

        diffstat_text = shortstat or _format_diffstat(manifest)
        changed_count = len(changed_paths)

        changeset = Changeset(
            schemaVersion=CHANGESET_SCHEMA_VERSION,
            dispatchId=dispatch_id,
            worktreePath=metadata.path,
            baseRef=metadata.baseRef,
            baseSha=base_sha,
            finalSha=final_sha,
            capturedAt=utc_now(),
            statusPorcelainV2=status_text,
            commits=commits,
            stagedPaths=staged,
            trackedPaths=tracked,
            untrackedPaths=untracked,
            binaryPaths=binary,
            manifest=manifest,
            diffstat=diffstat_text,
            numstat=numstat_text,
            changedFileCount=changed_count,
            patchPath=str(patch_path),
        )
        atomic_write_json(store.artifact("changeset.json"), changeset.to_dict())
        _ensure_integration_status(store, "not_applied")

    return changeset


def _list_commits(base_sha: str, final_sha: str, cwd: Path) -> list[dict[str, str]]:
    result = _run_git(
        ["log", "--reverse", "--pretty=format:%H%x09%s", f"{base_sha}..{final_sha}"],
        cwd=cwd,
    )
    text = result.stdout.decode("utf-8", errors="replace")
    commits: list[dict[str, str]] = []
    for line in text.splitlines():
        sha, _, subject = line.partition("\t")
        if not sha:
            continue
        commits.append({"sha": sha, "subject": subject})
    return commits


def load_worktree_metadata(env: Mapping[str, str], dispatch_id: str) -> WorktreeMetadata:
    _validate_dispatch_id(dispatch_id)
    path = _run_store(env, dispatch_id).artifact("workspace.json")
    if not path.is_file():
        raise OwnershipError(
            f"no isolated worktree recorded for dispatch {dispatch_id}; "
            "this dispatch did not use isolated mode"
        )
    metadata = _load_workspace_metadata(path)
    if metadata.schemaVersion != WORKSPACE_SCHEMA_VERSION:
        raise OwnershipError(
            f"workspace record schema {metadata.schemaVersion!r} is unsupported"
        )
    if metadata.dispatchId != dispatch_id or metadata.ownerDispatchId != dispatch_id:
        raise OwnershipError(
            f"workspace record does not belong to dispatch {dispatch_id}"
        )
    expected_branch = f"model-routing/{dispatch_id}"
    if metadata.branch != expected_branch:
        raise OwnershipError(
            f"workspace branch {metadata.branch!r} does not match owned branch {expected_branch!r}"
        )
    expected_path = worktree_path(env, dispatch_id).resolve()
    if Path(metadata.path).resolve() != expected_path:
        raise OwnershipError(
            f"workspace path {metadata.path!r} does not match owned path {expected_path}"
        )
    if not re_fullmatch_hex(metadata.baseSha):
        raise OwnershipError("workspace record has an invalid base commit")
    if not Path(metadata.repositoryCommonDir).is_absolute():
        raise OwnershipError("workspace repository common directory must be absolute")
    if not Path(metadata.sourceWorktree).is_absolute():
        raise OwnershipError("workspace source worktree must be absolute")
    common_dir = Path(metadata.repositoryCommonDir)
    if not common_dir.is_dir() or not (
        (common_dir / "HEAD").is_file() and (common_dir / "config").is_file()
    ):
        raise OwnershipError(
            f"recorded repository common directory is unavailable: {common_dir}; "
            "refusing apply/discard after a repository move"
        )
    return metadata


def _ensure_integration_status(store: RunStore, status: str) -> None:
    """Set ``result.json.integration.status`` if ``result.json`` exists.

    The terminal ``status`` of the dispatch is never changed here; only the
    integration field on the existing result document is updated.
    """
    result_path = store.artifact("result.json")
    if not result_path.is_file():
        return
    try:
        value = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(value, dict):
        return
    integration = value.get("integration")
    if not isinstance(integration, dict):
        return
    if integration.get("status") not in INTEGRATION_STATUSES:
        integration["status"] = status
    else:
        integration["status"] = status
    integration.setdefault("appliedAt", None)
    integration.setdefault("target", None)
    value["integration"] = integration
    atomic_write_json(result_path, value)


def inspect_run(env: Mapping[str, str], dispatch_id: str) -> dict[str, Any]:
    """Return a structured inspection payload for ``runs show``/``runs diff``."""
    _validate_dispatch_id(dispatch_id)
    store = _run_store(env, dispatch_id)
    inspection: dict[str, Any] = {"schemaVersion": 1, "dispatchId": dispatch_id}
    result_path = store.artifact("result.json")
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            inspection["status"] = result.get("status")
            inspection["result"] = result
        except (OSError, json.JSONDecodeError):
            inspection["result"] = None
    else:
        inspection["result"] = None

    changeset_path = store.artifact("changeset.json")
    if changeset_path.is_file():
        try:
            inspection["changeset"] = json.loads(changeset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            inspection["changeset"] = None
    else:
        inspection["changeset"] = None

    try:
        inspection["worktree"] = load_worktree_metadata(env, dispatch_id).to_dict()
    except OwnershipError:
        inspection["worktree"] = None

    return inspection


def apply_run(
    env: Mapping[str, str],
    dispatch_id: str,
    target_path: Path,
    *,
    apply_commits: bool = False,
) -> ApplyOutcome:
    """Apply a captured change set to a clean matching target repository."""
    _validate_dispatch_id(dispatch_id)
    metadata = load_worktree_metadata(env, dispatch_id)
    if metadata.ownerDispatchId != dispatch_id:
        raise OwnershipError(f"worktree is owned by {metadata.ownerDispatchId}, not {dispatch_id}")

    target = Path(target_path).resolve()
    target_common, target_work_tree = _repository_common_dir(target)
    if _canonical(target_common) != _canonical(Path(metadata.repositoryCommonDir)):
        raise RepositoryMismatchError(
            f"target repository {target_common} does not match recorded "
            f"repository {metadata.repositoryCommonDir}"
        )

    store = _run_store(env, dispatch_id)
    patch_path = store.artifact("changes.patch")
    if not patch_path.is_file():
        raise WorkspaceError(f"no captured patch for dispatch {dispatch_id}")
    try:
        changeset = json.loads(store.artifact("changeset.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"captured changeset is missing or corrupt: {exc}") from exc
    manifest = changeset.get("manifest") if isinstance(changeset, dict) else None
    if not isinstance(manifest, list):
        raise WorkspaceError("captured changeset has no valid path manifest")
    manifest_paths: set[str] = set()
    for entry in manifest:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
            raise OwnershipError(f"captured patch manifest contains an unsafe path: {path!r}")
        manifest_paths.add(path)
    for candidate in (patch_path, store.artifact("working.patch")):
        if not candidate.is_file() or not candidate.stat().st_size:
            continue
        parsed = _run_git(["apply", "--numstat", "-z", str(candidate)], cwd=target_work_tree, check=False)
        if parsed.returncode != 0:
            raise OwnershipError(f"captured patch cannot be parsed safely: {candidate}")
        patch_paths = {
            record.split(b"\t", 2)[2].decode("utf-8", errors="surrogateescape")
            for record in parsed.stdout.split(b"\0")
            if record and len(record.split(b"\t", 2)) == 3
        }
        unrecorded = sorted(patch_paths - manifest_paths)
        if unrecorded:
            raise OwnershipError(f"captured patch contains paths absent from its manifest: {unrecorded}")

    conflicted: list[str] = []
    applied_commits: list[str] = []
    message: str | None = None
    method = "cherry-pick" if apply_commits else "patch"
    identity: str | None = None

    with RepositoryLock(env, target_common):
        if not _status_is_clean(target_work_tree):
            raise DirtyTargetError(
                f"target worktree {target_work_tree} is dirty; "
                "commit, stash, or restore before applying changes"
            )

        if apply_commits:
            commits = changeset.get("commits", []) if isinstance(changeset, dict) else []
            for commit in commits:
                sha = commit["sha"]
                cp = _run_git(
                    ["cherry-pick", sha], cwd=target_work_tree, check=False
                )
                if cp.returncode != 0:
                    conflicted.extend(
                        _nul_paths(
                            _run_git(
                                ["diff", "--name-only", "--diff-filter=U", "-z"],
                                cwd=target_work_tree,
                                check=False,
                            ).stdout
                        )
                    )
                    message = (
                        f"cherry-pick conflict on commit {sha[:12]}; resolve it and run "
                        "`git cherry-pick --continue`, or cancel with `git cherry-pick --abort`"
                    )
                    break
                applied_commits.append(sha)
            if not conflicted:
                working_patch = store.artifact("working.patch")
                if working_patch.is_file() and working_patch.stat().st_size:
                    applied = _run_git(
                        ["apply", "--3way", "--whitespace=nowarn", str(working_patch)],
                        cwd=target_work_tree,
                        check=False,
                    )
                    if applied.returncode != 0:
                        conflicted = _nul_paths(
                            _run_git(["diff", "--name-only", "--diff-filter=U", "-z"], cwd=target_work_tree, check=False).stdout
                        ) or ["<patch>"]
                        message = "post-commit patch conflict; resolve manually"
            identity = applied_commits[-1] if applied_commits else None

        if not apply_commits:
            check_result = _run_git(
                ["apply", "--check", "--3way", str(patch_path)], cwd=target_work_tree, check=False
            )
            if patch_path.stat().st_size:
                argv = ["apply", "--whitespace=nowarn", str(patch_path)]
                if check_result.returncode != 0:
                    argv.insert(1, "--3way")
                applied = _run_git(argv, cwd=target_work_tree, check=False)
                if applied.returncode != 0:
                    conflicted = _nul_paths(
                        _run_git(["diff", "--name-only", "--diff-filter=U", "-z"], cwd=target_work_tree, check=False).stdout
                    ) or ["<patch>"]
                    message = "patch conflict; resolve manually"
            identity = hashlib.sha256(patch_path.read_bytes()).hexdigest()

        status = "conflicted" if conflicted else "applied"
        outcome = ApplyOutcome(
            status=status,
            appliedAt=utc_now(),
            target=_canonical(target_work_tree),
            appliedCommits=applied_commits,
            conflictedFiles=sorted(set(conflicted)),
            method=method,
            identity=identity,
            message=message,
        )
        _record_integration(store, outcome, metadata)

    return outcome


def _record_integration(
    store: RunStore,
    outcome: ApplyOutcome,
    metadata: WorktreeMetadata,
    *,
    required: bool = True,
) -> None:
    result_path = store.artifact("result.json")
    if not result_path.is_file() and not required:
        return
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if not required:
            return
        raise WorkspaceError(f"cannot update integration metadata: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("status") not in TERMINAL_DISPATCH_STATUSES:
        if not required:
            return
        raise WorkspaceError("result.json is not a terminal dispatch result")

    integration = payload.get("integration")
    if not isinstance(integration, dict):
        integration = {}

    integration.update(
        {
            "status": outcome.status,
            "appliedAt": outcome.appliedAt,
            "target": outcome.target,
            "method": outcome.method,
            "identity": outcome.identity,
            "conflictedFiles": outcome.conflictedFiles,
        }
    )
    payload["integration"] = integration
    atomic_write_json(result_path, payload)


def discard_run(env: Mapping[str, str], dispatch_id: str, *, yes: bool = False) -> WorktreeMetadata:
    """Discard the isolated worktree and branch owned by ``dispatch_id``."""
    _validate_dispatch_id(dispatch_id)
    metadata = load_worktree_metadata(env, dispatch_id)
    if metadata.ownerDispatchId != dispatch_id:
        raise OwnershipError(
            f"worktree {metadata.path} is owned by {metadata.ownerDispatchId}, not {dispatch_id}"
        )

    if not yes:
        raise UsageConfigurationError(
            "discard requires explicit confirmation; pass yes=True to acknowledge"
        )

    common_dir = Path(metadata.repositoryCommonDir)
    wt_path = Path(metadata.path)
    branch = metadata.branch
    store = _run_store(env, dispatch_id)

    with RepositoryLock(env, common_dir):
        # Refuse to delete anything that no longer matches our ownership record.
        current = _worktree_path_for_branch(common_dir, branch)
        if current is None:
            raise OwnershipError(
                f"owned branch {branch!r} is not attached to a live Git worktree; "
                "refusing filesystem fallback deletion"
            )
        if current.resolve() != wt_path.resolve():
            raise OwnershipError(
                f"recorded worktree path {wt_path} does not match current "
                f"worktree for branch {branch} at {current}"
            )
        metadata_path = store.artifact("workspace.json")
        if not metadata_path.is_file():
            raise OwnershipError(
                f"worktree {wt_path} no longer carries a workspace.json ownership record"
            )
        live = _load_workspace_metadata(metadata_path)
        if live.ownerDispatchId != dispatch_id or live.branch != branch:
            raise OwnershipError(
                f"worktree {wt_path} ownership record does not match this dispatch"
            )

        removed = _run_git(
            ["worktree", "remove", "--force", str(wt_path)],
            cwd=common_dir,
            check=False,
        )
        if removed.returncode != 0 or wt_path.exists():
            stderr = removed.stderr.decode("utf-8", errors="replace").strip()
            raise WorkspaceError(
                f"git refused to remove owned worktree {wt_path}: {stderr or 'path still exists'}"
            )
        _run_git(["worktree", "prune"], cwd=common_dir, check=False)
        deleted = _run_git(["branch", "-D", branch], cwd=common_dir, check=False)
        if deleted.returncode != 0 or _branch_exists(common_dir, branch):
            stderr = deleted.stderr.decode("utf-8", errors="replace").strip()
            raise WorkspaceError(
                f"git removed the worktree but could not delete owned branch {branch!r}: "
                f"{stderr or 'branch still exists'}"
            )
        outcome = ApplyOutcome(
            status="discarded",
            appliedAt=utc_now(),
            target=metadata.path,
            appliedCommits=[],
            conflictedFiles=[],
            method="discard",
            identity=metadata.branch,
            message=None,
        )
        _record_integration(store, outcome, metadata, required=False)

    return metadata


__all__ = [
    "ApplyOutcome",
    "BranchCollisionError",
    "Changeset",
    "DirtySourceError",
    "DirtyTargetError",
    "GitCommandError",
    "NotAGitRepositoryError",
    "OwnershipError",
    "RepositoryLock",
    "RepositoryMismatchError",
    "UsageConfigurationError",
    "WorkspaceError",
    "WorkspaceRequest",
    "WorktreeMetadata",
    "apply_run",
    "capture_changes",
    "discard_run",
    "inspect_run",
    "load_worktree_metadata",
    "prepare_isolated_worktree",
    "resolve_workspace",
    "worktree_path",
    "worktree_root",
]
