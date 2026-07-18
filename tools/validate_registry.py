#!/usr/bin/env python3
"""Validate the canonical provider registry without third-party dependencies."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.registry import RegistryError, load_registry  # noqa: E402


def main() -> int:
    registry_path = ROOT / "config" / "provider-registry.json"
    try:
        registry = load_registry(registry_path)
    except RegistryError as exc:
        print(f"provider registry invalid: {exc}", file=sys.stderr)
        return 1
    print(
        f"provider registry valid: {len(registry['providers'])} providers, "
        f"{len(registry['hosts'])} hosts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
