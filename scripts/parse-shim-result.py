#!/usr/bin/env python3
"""Print the authoritative trailing SHIM-RESULT receipt from shim stdout."""

import json
import re
import sys


def fail(message: str) -> None:
    print(f"parse-shim-result: {message}", file=sys.stderr)
    raise SystemExit(2)


lines = [line.rstrip("\r\n") for line in sys.stdin]
while lines and not lines[-1]:
    lines.pop()
if len(lines) < 2:
    fail("missing trailing receipt/sentinel pair")

result_line, done_line = lines[-2:]
done = re.fullmatch(r"SHIM-DONE exit=([0-9]+)", done_line)
if not done or not result_line.startswith("SHIM-RESULT "):
    fail("last two lines are not SHIM-RESULT then SHIM-DONE")

try:
    receipt = json.loads(result_line[len("SHIM-RESULT "):])
except json.JSONDecodeError as exc:
    fail(f"invalid receipt JSON: {exc.msg}")

if not isinstance(receipt, dict) or receipt.get("exit") != int(done.group(1)):
    fail("receipt exit does not match SHIM-DONE")

print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
