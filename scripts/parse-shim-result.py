#!/usr/bin/env python3
"""Print the authoritative trailing SHIM-RESULT receipt from shim stdout.

A dispatched child controls its own stdout and can print lines that look like
a receipt. Only the SHIM-RESULT immediately preceding the final SHIM-DONE was
written by the shim, so this reads the last two lines and nothing else, then
cross-checks the receipt's exit code against the sentinel's.

Reads shim stdout on stdin. Exits 0 and prints the receipt as compact JSON, or
exits 2 with the reason on stderr.
"""

from __future__ import annotations

import json
import re
import sys


SENTINEL = re.compile(r"SHIM-DONE exit=([0-9]+)")
PREFIX = "SHIM-RESULT "


def fail(message: str) -> int:
    print(f"parse-shim-result: {message}", file=sys.stderr)
    return 2


def main() -> int:
    lines = [line.rstrip("\r\n") for line in sys.stdin]
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) < 2:
        return fail("missing trailing receipt/sentinel pair")

    receipt_line, sentinel_line = lines[-2:]
    sentinel = SENTINEL.fullmatch(sentinel_line)
    if sentinel is None or not receipt_line.startswith(PREFIX):
        return fail("last two lines are not SHIM-RESULT then SHIM-DONE")

    try:
        receipt = json.loads(receipt_line[len(PREFIX):])
    except json.JSONDecodeError as exc:
        return fail(f"invalid receipt JSON: {exc.msg}")

    if not isinstance(receipt, dict):
        return fail("receipt is not a JSON object")
    if receipt.get("exit") != int(sentinel.group(1)):
        return fail("receipt exit does not match SHIM-DONE")

    print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
