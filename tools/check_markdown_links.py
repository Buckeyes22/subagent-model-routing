#!/usr/bin/env python3
"""Fail when a repository Markdown file contains a broken local link."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "data:", "app://")


def markdown_files() -> list[Path]:
    ignored = {".git", ".mypy_cache", ".ruff_cache", "node_modules"}
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(part in ignored for part in path.relative_to(ROOT).parts)
    )


def target_path(source: Path, raw_target: str) -> Path | None:
    target = raw_target[1:-1] if raw_target.startswith("<") else raw_target
    target = unquote(target).split("#", 1)[0]
    if not target or target.startswith(SKIP_PREFIXES):
        return None
    # Renderer-friendly absolute workspace links may include a trailing line number.
    target = re.sub(r":\d+$", "", target)
    candidate = Path(target)
    return candidate if candidate.is_absolute() else source.parent / candidate


def main() -> int:
    failures: list[str] = []
    checked = 0
    for source in markdown_files():
        text = source.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            candidate = target_path(source, match.group(1))
            if candidate is None:
                continue
            checked += 1
            if not candidate.exists():
                line = text.count("\n", 0, match.start()) + 1
                failures.append(
                    f"{source.relative_to(ROOT)}:{line}: broken local link {match.group(1)}"
                )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"validated {checked} local links across {len(markdown_files())} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
