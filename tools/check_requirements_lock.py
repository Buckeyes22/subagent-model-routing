#!/usr/bin/env python3
"""Fail when requirements-dev.lock no longer matches requirements-dev.txt.

Every install path in this repository resolves requirements-dev.lock, not
requirements-dev.txt. A bump that edits only the .txt therefore changes
nothing, and CI stays green while reporting the old versions. Dependabot
cannot regenerate this lock -- it is uv output, not pip-compile output, and
the file is not named *.txt -- so the drift has to be caught here.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-dev.txt"
LOCK = ROOT / "requirements-dev.lock"
PIN = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)")
REGENERATE = (
    "uv pip compile --universal --generate-hashes "
    "requirements-dev.txt --output-file requirements-dev.lock"
)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PIN.match(stripped)
        if match:
            found.setdefault(canonical(match.group(1)), match.group(2))
    return found


def main() -> int:
    declared = pins(REQUIREMENTS)
    locked = pins(LOCK)
    problems = []
    for name, version in sorted(declared.items()):
        if name not in locked:
            problems.append(f"{name}=={version} is declared but absent from the lock")
        elif locked[name] != version:
            problems.append(f"{name} is pinned at {version} but locked at {locked[name]}")
    if problems:
        print("requirements-dev.lock is stale:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(f"\nregenerate with:\n  {REGENERATE}", file=sys.stderr)
        return 1
    print(f"requirements-dev.lock matches all {len(declared)} declared pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
