#!/usr/bin/env bash
# opencode-shim.sh - standalone transport shim: one-shot `opencode run` dispatch.
#
# Usage:
#   opencode-shim.sh <provider/model> <prompt-source> [extra opencode-run args]
#     <provider/model> route target, as listed by `opencode models`
#     <prompt-source>  filepath, or "-" to read the prompt from stdin
#
# Contract:
#   - stdout = opencode output; exit code = opencode's exit code
#   - the LAST stdout line is always "SHIM-DONE exit=<n>" on its own line (a preceding blank line may appear)
#   - appends started/finished JSONL records to the routing ledger
#   - dispatch-level failures before a run begins (usage errors, missing timeout binary) emit only the sentinel, no ledger records
#
# Env:
#   SHIM_TIMEOUT_SECS           child wall ceiling (default 1140, about 19 min)
#   SUBAGENT_MODEL_ROUTING_UNRESTRICTED  1 (default) = allow opencode to run without prompts
#   SUBAGENT_MODEL_ROUTING_LEDGER        default ~/.claude/subagent-model-routing/ledger/observations.jsonl
#   OPENCODE_BIN                optional opencode executable override
#   OPENCODE_OTLP_ENDPOINT      optional OTLP collector; setting it enables opencode telemetry (see README Observability)
set -u

if [ "$#" -lt 2 ]; then
  echo "opencode-shim: usage: opencode-shim.sh <provider/model> <prompt-source> [extra opencode-run args]" >&2
  echo "SHIM-DONE exit=64"
  exit 64
fi

MODEL="$1"
SOURCE="$2"
shift 2

TIMEOUT_SECS="${SHIM_TIMEOUT_SECS:-1140}"
UNRESTRICTED="${SUBAGENT_MODEL_ROUTING_UNRESTRICTED:-1}"
LEDGER="${SUBAGENT_MODEL_ROUTING_LEDGER:-$HOME/.claude/subagent-model-routing/ledger/observations.jsonl}"

json_escape() {
  local value
  value=${1//$'\r'/ }
  value=${value//$'\n'/ }
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '%s' "$value"
}

MODEL_JSON="$(json_escape "$MODEL")"

now() { date -u +%Y-%m-%dT%H:%M:%S; }
ledger_append() {
  mkdir -p "$(dirname "$LEDGER")" 2>/dev/null || return 0
  printf '%s\n' "$1" >> "$LEDGER" 2>/dev/null || true
}

if [ -n "${OPENCODE_BIN:-}" ]; then
  OPENCODE_BIN_RESOLVED="$OPENCODE_BIN"
elif OPENCODE_BIN_RESOLVED="$(command -v opencode 2>/dev/null)"; then
  :
elif [ -x "$HOME/.opencode/bin/opencode" ]; then
  OPENCODE_BIN_RESOLVED="$HOME/.opencode/bin/opencode"
else
  echo "opencode-shim: opencode CLI not found" >&2
  ledger_append "{\"ts\":\"$(now)\",\"shim\":\"opencode\",\"model\":\"$MODEL_JSON\",\"event\":\"finished\",\"exit\":127,\"wall_s\":0,\"outcome\":\"error\",\"source\":\"shim\"}"
  echo "SHIM-DONE exit=127"
  exit 127
fi

if TIMEOUT_BIN="$(command -v timeout 2>/dev/null)"; then
  :
elif TIMEOUT_BIN="$(command -v gtimeout 2>/dev/null)"; then
  :
else
  echo "opencode-shim: GNU timeout not found (brew install coreutils provides gtimeout)" >&2
  echo "SHIM-DONE exit=127"
  exit 127
fi

PERM_FLAG=""
if [ "$UNRESTRICTED" = "1" ]; then
  HELP="$("$OPENCODE_BIN_RESOLVED" run --help 2>&1 || true)"
  case "$HELP" in
    *--dangerously-skip-permissions*) PERM_FLAG="--dangerously-skip-permissions" ;;
    *--auto*) PERM_FLAG="--auto" ;;
  esac
fi

# Optional observability: when the user points opencode at an OTLP collector,
# default the companion telemetry vars. Inert when OPENCODE_OTLP_ENDPOINT is unset.
if [ -n "${OPENCODE_OTLP_ENDPOINT:-}" ]; then
  : "${OPENCODE_ENABLE_TELEMETRY:=1}"
  : "${OPENCODE_OTLP_PROTOCOL:=http/protobuf}"
  : "${OPENCODE_RESOURCE_ATTRIBUTES:=service.name=opencode}"
  export OPENCODE_ENABLE_TELEMETRY OPENCODE_OTLP_PROTOCOL OPENCODE_OTLP_ENDPOINT OPENCODE_RESOURCE_ATTRIBUTES
fi

t0=$(date +%s)
ledger_append "{\"ts\":\"$(now)\",\"shim\":\"opencode\",\"model\":\"$MODEL_JSON\",\"event\":\"started\",\"source\":\"shim\"}"

if [ "$SOURCE" = "-" ]; then
  "$TIMEOUT_BIN" "$TIMEOUT_SECS" "$OPENCODE_BIN_RESOLVED" run -m "$MODEL" ${PERM_FLAG:+"$PERM_FLAG"} "$@"
  rc=$?
else
  if [ ! -r "$SOURCE" ]; then
    echo "opencode-shim: cannot read $SOURCE" >&2
    ledger_append "{\"ts\":\"$(now)\",\"shim\":\"opencode\",\"model\":\"$MODEL_JSON\",\"event\":\"finished\",\"exit\":66,\"wall_s\":0,\"outcome\":\"error\",\"source\":\"shim\"}"
    echo "SHIM-DONE exit=66"
    exit 66
  fi
  "$TIMEOUT_BIN" "$TIMEOUT_SECS" "$OPENCODE_BIN_RESOLVED" run -m "$MODEL" ${PERM_FLAG:+"$PERM_FLAG"} "$@" < "$SOURCE"
  rc=$?
fi

wall=$(( $(date +%s) - t0 ))
outcome="ok"
[ "$rc" -eq 124 ] && outcome="timeout"
[ "$rc" -ne 0 ] && [ "$rc" -ne 124 ] && outcome="error"
ledger_append "{\"ts\":\"$(now)\",\"shim\":\"opencode\",\"model\":\"$MODEL_JSON\",\"event\":\"finished\",\"exit\":$rc,\"wall_s\":$wall,\"outcome\":\"$outcome\",\"source\":\"shim\"}"
printf '\nSHIM-DONE exit=%s\n' "$rc"
exit "$rc"
