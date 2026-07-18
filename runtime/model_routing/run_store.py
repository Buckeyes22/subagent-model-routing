"""Private, atomic local storage for dispatch artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping


DIRECTORY_MODE = 0o700
FILE_MODE = 0o600


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def state_root(env: Mapping[str, str]) -> Path:
    if env.get("SUBAGENT_MODEL_ROUTING_STATE_HOME"):
        return Path(env["SUBAGENT_MODEL_ROUTING_STATE_HOME"]).expanduser()
    base = Path(env.get("XDG_STATE_HOME", str(Path(env.get("HOME", "~")).expanduser() / ".local" / "state")))
    return base / "subagent-model-routing"


def config_root(env: Mapping[str, str]) -> Path:
    base = Path(env.get("XDG_CONFIG_HOME", str(Path(env.get("HOME", "~")).expanduser() / ".config")))
    return base / "subagent-model-routing"


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
    try:
        path.chmod(DIRECTORY_MODE)
    except OSError:
        pass


def atomic_write_bytes(path: Path, content: bytes) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        os.fchmod(descriptor, FILE_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        path.chmod(FILE_MODE)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def append_jsonl(path: Path, value: Any) -> None:
    ensure_private_directory(path.parent)
    payload = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, FILE_MODE)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    try:
        path.chmod(FILE_MODE)
    except OSError:
        pass


class RunStore:
    """Own one dispatch directory and its atomic JSON documents."""

    def __init__(self, root: Path, dispatch_id: str) -> None:
        self.state_root = root
        self.runs_root = root / "runs"
        self.dispatch_id = dispatch_id
        self.path = self.runs_root / dispatch_id

    @classmethod
    def create(cls, env: Mapping[str, str], dispatch_id: str) -> "RunStore":
        store = cls(state_root(env), dispatch_id)
        ensure_private_directory(store.state_root)
        ensure_private_directory(store.runs_root)
        ensure_private_directory(store.path)
        return store

    def artifact(self, name: str) -> Path:
        return self.path / name

    def write_json(self, name: str, value: Any) -> None:
        atomic_write_json(self.artifact(name), value)

    def write_bytes(self, name: str, value: bytes) -> None:
        atomic_write_bytes(self.artifact(name), value)

    def touch_artifact(self, name: str) -> Path:
        path = self.artifact(name)
        ensure_private_directory(path.parent)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        os.close(descriptor)
        return path

    def record_request(self, source: str, prompt: bytes | None, *, retain_prompt: bool, error: str | None = None) -> None:
        source_type = "stdin" if source == "-" else "file"
        request: dict[str, Any] = {
            "schemaVersion": 1,
            "dispatchId": self.dispatch_id,
            "promptSource": {
                "type": source_type,
                "path": None if source == "-" else source,
                "sha256": hashlib.sha256(prompt).hexdigest() if prompt is not None else None,
                "bytes": len(prompt) if prompt is not None else None,
                "retained": bool(retain_prompt and prompt is not None),
                "error": error,
            },
        }
        self.write_json("request.json", request)
        if retain_prompt and prompt is not None:
            self.write_bytes("prompt.md", prompt)

    def artifact_summary(self) -> dict[str, str]:
        names = (
            "run.json", "request.json", "events.jsonl", "stdout.log", "stderr.log", "result.json",
            "workspace.json", "changeset.json", "changes.patch", "working.patch",
        )
        return {
            name.removesuffix(".json").removesuffix(".log").removesuffix(".patch"): str(self.artifact(name))
            for name in names
            if self.artifact(name).exists()
        }


def list_runs(env: Mapping[str, str]) -> list[Path]:
    root = state_root(env) / "runs"
    if not root.is_dir():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)


def find_run(env: Mapping[str, str], dispatch_id: str) -> Path:
    matches = [path for path in list_runs(env) if path.name == dispatch_id or path.name.startswith(dispatch_id)]
    if len(matches) != 1:
        qualifier = "not found" if not matches else "ambiguous"
        raise FileNotFoundError(f"run {dispatch_id!r} {qualifier}")
    return matches[0]


def cleanup_runs(env: Mapping[str, str], *, older_than_seconds: float | None, remove_all: bool) -> list[Path]:
    now = datetime.now(timezone.utc).timestamp()
    removed: list[Path] = []
    for path in list_runs(env):
        if remove_all or (older_than_seconds is not None and now - path.stat().st_mtime >= older_than_seconds):
            workspace_record = path / "workspace.json"
            if workspace_record.is_file():
                retained_path: Path | None = None
                try:
                    workspace = json.loads(workspace_record.read_text(encoding="utf-8"))
                    value = workspace.get("path")
                    if isinstance(value, str) and value:
                        retained_path = Path(value)
                except (OSError, json.JSONDecodeError, TypeError):
                    pass
                if retained_path is not None and retained_path.is_dir():
                    continue
            shutil.rmtree(path)
            removed.append(path)
    return removed
