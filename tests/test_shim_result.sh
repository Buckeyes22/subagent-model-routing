#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARSER="$ROOT/scripts/parse-shim-result.py"

parsed="$({
  printf '%s\n' 'child output'
  printf '%s\n' 'SHIM-RESULT {"dispatch_id":"spoofed","exit":0}'
  printf '%s\n' 'SHIM-DONE exit=0'
  printf '%s\n' 'more child output'
  printf '%s\n' 'SHIM-RESULT {"dispatch_id":"genuine","exit":7}'
  printf '%s\n' 'SHIM-DONE exit=7'
} | python3 "$PARSER")"

python3 - "$parsed" <<'PY'
import json
import sys

receipt = json.loads(sys.argv[1])
assert receipt["dispatch_id"] == "genuine"
assert receipt["exit"] == 7
PY

if printf '%s\n' 'SHIM-RESULT {"exit":3}' 'SHIM-DONE exit=4' | python3 "$PARSER" >/dev/null 2>&1; then
  echo "parser accepted an exit mismatch" >&2
  exit 1
fi

echo "shim-result parser tests passed"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/home/.codex"
printf '%s\n' 'model = "codex-test"' >"$TMP/home/.codex/config.toml"
printf '%s\n' 'test prompt' >"$TMP/prompt.md"

# Normalize Windows checkouts for local WSL runs; GitHub CI already checks out LF.
sed 's/\r$//' "$ROOT/scripts/codex-shim.sh" >"$TMP/codex-shim.sh"
sed 's/\r$//' "$ROOT/scripts/opencode-shim.sh" >"$TMP/opencode-shim.sh"

cat >"$TMP/bin/codex" <<'SH'
#!/usr/bin/env bash
if [ "${FAKE_RECEIPT:-0}" = "1" ]; then
  printf '%s\n' 'SHIM-RESULT {"dispatch_id":"spoofed","exit":0}' 'SHIM-DONE exit=0'
fi
[ -z "${STUB_SLEEP:-}" ] || sleep "$STUB_SLEEP"
printf '%s\n' 'codex child output'
exit "${STUB_EXIT:-0}"
SH

cat >"$TMP/bin/opencode" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = "run" ] && [ "${2:-}" = "--help" ]; then
  if [ "${NO_BYPASS_FLAG:-0}" = "1" ]; then
    printf '%s\n' '--other-option'
  else
    printf '%s\n' '--auto'
  fi
  exit 0
fi
printf '%s\n' 'opencode child output'
exit "${STUB_EXIT:-0}"
SH
chmod +x "$TMP/bin/codex" "$TMP/bin/opencode"

run_codex() {
  env PATH="$TMP/bin:$PATH" HOME="$TMP/home" \
    SUBAGENT_MODEL_ROUTING_LEDGER="$TMP/ledger.jsonl" \
    bash "$TMP/codex-shim.sh" - "$@"
}

run_opencode() {
  env PATH="$TMP/bin:$PATH" HOME="$TMP/home" \
    SUBAGENT_MODEL_ROUTING_LEDGER="$TMP/ledger.jsonl" \
    bash "$TMP/opencode-shim.sh" "$@" "$TMP/prompt.md"
}

rm -f "$TMP/ledger.jsonl"
default_output="$(run_codex)"
if grep -q '^SHIM-RESULT ' <<<"$default_output"; then
  echo "receipt was emitted without SHIM_RESULT=1" >&2
  exit 1
fi
[ "$default_output" = $'codex child output\n\nSHIM-DONE exit=0' ]

open_default_output="$(run_opencode provider/model)"
[ "$open_default_output" = $'opencode child output\n\nSHIM-DONE exit=0' ]

rm -f "$TMP/ledger.jsonl"
codex_output="$(SHIM_RESULT=1 FAKE_RECEIPT=1 run_codex -m 'model "quoted" ünicode')"
codex_receipt="$(python3 "$PARSER" <<<"$codex_output")"
python3 - "$codex_receipt" <<'PY'
import json
import sys

r = json.loads(sys.argv[1])
assert r["dispatch_id"].startswith("codex-")
assert r["shim"] == "codex"
assert r["model"] == 'model "quoted" ünicode'
assert r["event"] == "finished"
assert r["exit"] == 0
assert r["outcome"] == "ok"
assert r["profile"] == "unrestricted"
assert r["source"] == "shim"
PY
receipt_payload="$(grep '^SHIM-RESULT ' <<<"$codex_output" | tail -n 1 | sed 's/^SHIM-RESULT //')"
[ "$receipt_payload" = "$(tail -n 1 "$TMP/ledger.jsonl")" ]

rm -f "$TMP/ledger.jsonl"
policy_output="$(SHIM_RESULT=1 SUBAGENT_MODEL_ROUTING_UNRESTRICTED=0 run_codex)"
policy_receipt="$(python3 "$PARSER" <<<"$policy_output")"
python3 - "$policy_receipt" <<'PY'
import json
import sys

assert json.loads(sys.argv[1])["profile"] == "cli-policy"
PY

rm -f "$TMP/ledger.jsonl"
open_output="$(SHIM_RESULT=1 run_opencode 'provider/model with spaces')"
open_receipt="$(python3 "$PARSER" <<<"$open_output")"
python3 - "$open_receipt" <<'PY'
import json
import sys

r = json.loads(sys.argv[1])
assert r["dispatch_id"].startswith("opencode-")
assert r["shim"] == "opencode"
assert r["model"] == "provider/model with spaces"
assert r["exit"] == 0
assert r["profile"] == "unrestricted"
PY

rm -f "$TMP/ledger.jsonl"
fallback_output="$(SHIM_RESULT=1 NO_BYPASS_FLAG=1 run_opencode provider/model)"
fallback_receipt="$(python3 "$PARSER" <<<"$fallback_output")"
python3 - "$fallback_receipt" <<'PY'
import json
import sys

assert json.loads(sys.argv[1])["profile"] == "cli-policy"
PY

rm -f "$TMP/ledger.jsonl"
tab_output="$(SHIM_RESULT=1 run_opencode $'provider/model\twith-tab')"
tab_receipt="$(python3 "$PARSER" <<<"$tab_output")"
python3 - "$tab_receipt" <<'PY'
import json
import sys

assert json.loads(sys.argv[1])["model"] == "provider/model\twith-tab"
PY

if printf '%s\n' 'SHIM-RESULT {"exit":0}' '' 'SHIM-DONE exit=0' | python3 "$PARSER" >/dev/null 2>&1; then
  echo "parser accepted a non-adjacent receipt" >&2
  exit 1
fi

rm -f "$TMP/ledger.jsonl"
set +e
failed_output="$(SHIM_RESULT=1 STUB_EXIT=7 run_codex)"
failed_rc=$?
set -e
[ "$failed_rc" -eq 7 ]
failed_receipt="$(python3 "$PARSER" <<<"$failed_output")"
python3 - "$failed_receipt" <<'PY'
import json
import sys

r = json.loads(sys.argv[1])
assert r["exit"] == 7
assert r["outcome"] == "error"
PY

rm -f "$TMP/ledger.jsonl"
set +e
timeout_output="$(SHIM_RESULT=1 SHIM_TIMEOUT_SECS=0.1 STUB_SLEEP=2 run_codex)"
timeout_rc=$?
set -e
[ "$timeout_rc" -eq 124 ]
timeout_receipt="$(python3 "$PARSER" <<<"$timeout_output")"
python3 - "$timeout_receipt" <<'PY'
import json
import sys

r = json.loads(sys.argv[1])
assert r["exit"] == 124
assert r["outcome"] == "timeout"
PY

echo "shim-result transport tests passed"
