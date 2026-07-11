#!/usr/bin/env bash
# codex-shim.sh - standalone transport shim: one-shot `codex exec` dispatch.
#
# Usage:
#   codex-shim.sh <prompt-source> [extra codex-exec args]
#     <prompt-source>  filepath, or "-" to read the prompt from stdin
#
# Contract:
#   - stdout = codex output; exit code = codex's exit code
#   - the LAST stdout line is always "SHIM-DONE exit=<n>" on its own line (a preceding blank line may appear)
#   - appends started/finished JSONL records to the routing ledger
#   - dispatch-level failures before a run begins (usage errors, missing timeout binary) emit only the sentinel, no ledger records
#
# Env:
#   SHIM_TIMEOUT_SECS           child wall ceiling (default 1140, about 19 min)
#   SHIM_RESULT                 1 = emit a machine-readable SHIM-RESULT receipt before SHIM-DONE
#   SUBAGENT_MODEL_ROUTING_UNRESTRICTED  1 (default) = bypass codex sandbox/approvals
#                               (see README security note); 0 = --sandbox workspace-write
#   SUBAGENT_MODEL_ROUTING_LEDGER        default ~/.claude/subagent-model-routing/ledger/observations.jsonl
#   OTEL_RESOURCE_ATTRIBUTES    optional; the shim appends gen_ai.request.model=<model> for span attribution (see README Observability)
set -u

if [ "$#" -lt 1 ]; then
  echo "codex-shim: usage: codex-shim.sh <prompt-source> [extra codex-exec args]" >&2
  echo "SHIM-DONE exit=64"
  exit 64
fi

SOURCE="$1"
shift

TIMEOUT_SECS="${SHIM_TIMEOUT_SECS:-1140}"
RESULT_ENABLED="${SHIM_RESULT:-0}"
UNRESTRICTED="${SUBAGENT_MODEL_ROUTING_UNRESTRICTED:-1}"
LEDGER="${SUBAGENT_MODEL_ROUTING_LEDGER:-$HOME/.claude/subagent-model-routing/ledger/observations.jsonl}"

if TIMEOUT_BIN="$(command -v timeout 2>/dev/null)"; then
  :
elif TIMEOUT_BIN="$(command -v gtimeout 2>/dev/null)"; then
  :
else
  echo "codex-shim: GNU timeout not found (brew install coreutils provides gtimeout)" >&2
  echo "SHIM-DONE exit=127"
  exit 127
fi

# Model label for the ledger: the user's config default unless an override is forwarded.
MODEL="$(sed -n 's/^model *= *"\(.*\)".*/\1/p' "$HOME/.codex/config.toml" 2>/dev/null | head -1)"
MODEL="${MODEL:-codex-default}"
_prev=""
for _a in "$@"; do
  case "$_prev" in -m|--model) MODEL="$_a" ;; esac
  case "$_a" in model=*) MODEL="${_a#model=}" ;; esac
  _prev="$_a"
done

# Span attribution: codex emits usage but no model attribute; its OTel SDK honors
# OTEL_RESOURCE_ATTRIBUTES. Inert unless the user runs an OTel collector.
export OTEL_RESOURCE_ATTRIBUTES="${OTEL_RESOURCE_ATTRIBUTES:+${OTEL_RESOURCE_ATTRIBUTES},}gen_ai.request.model=${MODEL}"

json_escape() {
  local value
  value=${1//$'\r'/ }
  value=${value//$'\n'/ }
  value=${value//\\/\\\\}
  value=${value//$'\b'/\\b}
  value=${value//$'\f'/\\f}
  value=${value//$'\t'/\\t}
  value=${value//\"/\\\"}
  printf '%s' "$value"
}

MODEL_JSON="$(json_escape "$MODEL")"

ARGS=(exec --skip-git-repo-check)
if [ "$UNRESTRICTED" = "1" ]; then
  PROFILE="unrestricted"
  ARGS+=(--dangerously-bypass-approvals-and-sandbox)
else
  PROFILE="cli-policy"
  ARGS+=(--sandbox workspace-write)
fi

now() { date -u +%Y-%m-%dT%H:%M:%S; }
ledger_append() {
  mkdir -p "$(dirname "$LEDGER")" 2>/dev/null || return 0
  printf '%s\n' "$1" >> "$LEDGER" 2>/dev/null || true
}

t0=$(date +%s)
DISPATCH_ID="codex-$t0-$$"
ledger_append "{\"ts\":\"$(now)\",\"dispatch_id\":\"$DISPATCH_ID\",\"shim\":\"codex\",\"model\":\"$MODEL_JSON\",\"event\":\"started\",\"profile\":\"$PROFILE\",\"source\":\"shim\"}"

if [ "$SOURCE" = "-" ]; then
  "$TIMEOUT_BIN" "$TIMEOUT_SECS" codex "${ARGS[@]}" "$@"
  rc=$?
else
  if [ ! -r "$SOURCE" ]; then
    echo "codex-shim: cannot read $SOURCE" >&2
    ledger_append "{\"ts\":\"$(now)\",\"shim\":\"codex\",\"model\":\"$MODEL_JSON\",\"event\":\"finished\",\"exit\":66,\"wall_s\":0,\"outcome\":\"error\",\"source\":\"shim\"}"
    echo "SHIM-DONE exit=66"
    exit 66
  fi
  "$TIMEOUT_BIN" "$TIMEOUT_SECS" codex "${ARGS[@]}" "$@" < "$SOURCE"
  rc=$?
fi

wall=$(( $(date +%s) - t0 ))
outcome="ok"
[ "$rc" -eq 124 ] && outcome="timeout"
[ "$rc" -ne 0 ] && [ "$rc" -ne 124 ] && outcome="error"
finished="{\"ts\":\"$(now)\",\"dispatch_id\":\"$DISPATCH_ID\",\"shim\":\"codex\",\"model\":\"$MODEL_JSON\",\"event\":\"finished\",\"exit\":$rc,\"wall_s\":$wall,\"outcome\":\"$outcome\",\"profile\":\"$PROFILE\",\"source\":\"shim\"}"
ledger_append "$finished"
if [ "$RESULT_ENABLED" = "1" ]; then
  printf '\nSHIM-RESULT %s\n' "$finished"
else
  printf '\n'
fi
printf 'SHIM-DONE exit=%s\n' "$rc"
exit "$rc"
