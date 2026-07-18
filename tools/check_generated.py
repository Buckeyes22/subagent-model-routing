#!/usr/bin/env python3
"""CI entrypoint for checking committed generated assets."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.sync_routes import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["--check"]))
