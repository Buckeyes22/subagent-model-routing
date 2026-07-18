#!/usr/bin/env python3
"""Build a deterministic, privacy-checked public release snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "public-release-files.json"
RELEASE_MANIFEST = "PUBLIC-RELEASE-MANIFEST.json"
EXPECTED_CONFIG_KEYS = {"schemaVersion", "files", "directories", "excludeGlobs"}
PRIVATE_TEXT_PATTERNS = {
    "maintainer home path": re.compile(
        r"/(?:home|Users)/(?!user/|example/|runner/)[a-z0-9][a-z0-9._-]*/",
        re.IGNORECASE,
    ),
    "private infrastructure domain": re.compile(
        r"ssh://git@(?!github\.com\b|gitlab\.com\b|bitbucket\.org\b)[a-z0-9.-]+",
        re.IGNORECASE,
    ),
    "personal Proton Mail address": re.compile(r"[a-z0-9._%+-]+@protonmail\.com", re.IGNORECASE),
    "private key material": re.compile(
        "-----BEGIN " + r"(?:OPENSSH |RSA |EC |DSA )?" + "PRIVATE KEY-----"
    ),
}


class PublicReleaseError(ValueError):
    """The configured release set is unsafe or incomplete."""


def _load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PublicReleaseError(f"cannot read release config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PublicReleaseError(f"invalid release config {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != EXPECTED_CONFIG_KEYS:
        raise PublicReleaseError(
            "release config must contain exactly schemaVersion, files, directories, and excludeGlobs"
        )
    if value.get("schemaVersion") != 1:
        raise PublicReleaseError("release config schemaVersion must be 1")
    for field in ("files", "directories", "excludeGlobs"):
        entries = value.get(field)
        if not isinstance(entries, list) or not all(isinstance(item, str) and item for item in entries):
            raise PublicReleaseError(f"release config {field} must be a list of non-empty strings")
        if len(entries) != len(set(entries)):
            raise PublicReleaseError(f"release config {field} must not contain duplicates")
    return value


def _safe_relative(value: str, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PublicReleaseError(f"{field} contains an unsafe path: {value!r}")
    return path


def _excluded(relative: Path, patterns: Iterable[str]) -> bool:
    candidate = PurePosixPath(relative.as_posix())
    return any(candidate.match(pattern) for pattern in patterns)


def collect_release_files(source_root: Path, config: dict[str, Any]) -> tuple[Path, ...]:
    """Return the sorted, duplicate-free set of allowlisted regular files."""

    selected: set[Path] = set()
    patterns = tuple(config["excludeGlobs"])
    for raw in config["files"]:
        relative = _safe_relative(raw, "files")
        source = source_root / relative
        if not source.is_file() or source.is_symlink():
            raise PublicReleaseError(f"allowlisted file is missing or not a regular file: {relative}")
        if not _excluded(relative, patterns):
            selected.add(relative)
    for raw in config["directories"]:
        directory = _safe_relative(raw, "directories")
        source_directory = source_root / directory
        if not source_directory.is_dir() or source_directory.is_symlink():
            raise PublicReleaseError(f"allowlisted directory is missing or unsafe: {directory}")
        for source in source_directory.rglob("*"):
            relative = source.relative_to(source_root)
            if _excluded(relative, patterns):
                continue
            if source.is_symlink():
                raise PublicReleaseError(f"release input must not contain symlinks: {relative}")
            if source.is_file():
                selected.add(relative)
    return tuple(sorted(selected, key=lambda path: path.as_posix()))


def private_text_findings(path: Path, text: str) -> tuple[str, ...]:
    """Return privacy-rule names matched by one candidate file."""

    del path  # Kept in the API so future path-specific allow rules remain explicit.
    return tuple(name for name, pattern in PRIVATE_TEXT_PATTERNS.items() if pattern.search(text))


def _validate_candidate_file(source: Path, relative: Path) -> None:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PublicReleaseError(f"public release inputs must be UTF-8 text: {relative}") from exc
    findings = private_text_findings(relative, text)
    if findings:
        raise PublicReleaseError(f"private content in {relative}: {', '.join(findings)}")


def _file_record(path: Path, relative: Path) -> dict[str, Any]:
    content = path.read_bytes()
    mode = path.stat().st_mode
    return {
        "path": relative.as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "executable": bool(mode & stat.S_IXUSR),
    }


def build_release(
    source_root: Path,
    destination: Path,
    *,
    config_path: Path | None = None,
) -> tuple[Path, ...]:
    """Copy the public allowlist atomically into a new external directory."""

    source_root = source_root.resolve()
    destination = destination.resolve()
    if destination == source_root or source_root in destination.parents:
        raise PublicReleaseError("release destination must be outside the source repository")
    if destination.exists():
        raise PublicReleaseError(f"release destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    config_file = (config_path or source_root / "config" / "public-release-files.json").resolve()
    config = _load_config(config_file)
    files = collect_release_files(source_root, config)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        records: list[dict[str, Any]] = []
        for relative in files:
            source = source_root / relative
            _validate_candidate_file(source, relative)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            records.append(_file_record(target, relative))
        manifest = {
            "schemaVersion": 1,
            "fileCount": len(records),
            "files": records,
        }
        (temporary / RELEASE_MANIFEST).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new output directory outside the repository")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        files = build_release(args.source_root, args.destination, config_path=args.config)
    except PublicReleaseError as exc:
        parser.error(str(exc))
    print(f"built public release snapshot with {len(files)} files at {args.destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
