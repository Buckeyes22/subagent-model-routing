#!/usr/bin/env bash
# bootstrap.sh - clone/update subagent-model-routing, install shims, and print/register plugins.
#
# Env overrides:
#   SUBAGENT_MODEL_ROUTING_HOME        clone location (default: "$HOME/.local/share/subagent-model-routing")
#   SUBAGENT_MODEL_ROUTING_REPO_URL    git source (default: "https://github.com/Buckeyes22/subagent-model-routing")
#   SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR shim install dir passed to install.sh; when unset,
#                             install.sh uses its default "$HOME/.claude/scripts"
set -euo pipefail

REGISTER=0
for arg in "$@"; do
  case "$arg" in
    --register) REGISTER=1 ;;
    -h|--help) echo "Usage: bootstrap.sh [--register]"; exit 0 ;;
    *) echo "error: unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v git >/dev/null 2>&1; then
  echo "error: git is required but was not found on PATH" >&2
  exit 1
fi

SUBAGENT_MODEL_ROUTING_HOME="${SUBAGENT_MODEL_ROUTING_HOME:-$HOME/.local/share/subagent-model-routing}"
SUBAGENT_MODEL_ROUTING_REPO_URL="${SUBAGENT_MODEL_ROUTING_REPO_URL:-https://github.com/Buckeyes22/subagent-model-routing}"

cmd_text() {
  local out="" q arg
  for arg in "$@"; do
    printf -v q "%q" "$arg"; out="${out}${out:+ }${q}"
  done
  printf "%s" "$out"
}

run_or_print() {
  if [ "$REGISTER" -eq 1 ]; then
    echo "+ $(cmd_text "$@")"
    "$@"
  else
    echo "  $(cmd_text "$@")"
  fi
}

handle_client() {
  local client="$1"
  local -a cmd1 cmd2
  case "$client" in
    claude)
      cmd1=(claude plugin marketplace add "$SUBAGENT_MODEL_ROUTING_HOME" --scope user)
      cmd2=(claude plugin install subagent-model-routing-claude@subagent-model-routing --scope user) ;;
    codex)
      cmd1=(codex plugin marketplace add "$SUBAGENT_MODEL_ROUTING_HOME")
      cmd2=(codex plugin add subagent-model-routing-codex@subagent-model-routing-local) ;;
    copilot)
      cmd1=(copilot plugin marketplace add "$SUBAGENT_MODEL_ROUTING_HOME")
      cmd2=(copilot plugin install subagent-model-routing-copilot@subagent-model-routing-local) ;;
  esac
  if command -v "$client" >/dev/null 2>&1; then
    echo "$client CLI detected:"
    run_or_print "${cmd1[@]}"
    run_or_print "${cmd2[@]}"
  else
    echo "$client CLI not found; run later: $(cmd_text "${cmd1[@]}") && $(cmd_text "${cmd2[@]}")"
  fi
}

if [ -d "$SUBAGENT_MODEL_ROUTING_HOME/.git" ]; then
  echo "Updating subagent-model-routing at $SUBAGENT_MODEL_ROUTING_HOME"; git -C "$SUBAGENT_MODEL_ROUTING_HOME" pull --ff-only
else
  echo "Cloning subagent-model-routing into $SUBAGENT_MODEL_ROUTING_HOME"; mkdir -p "$(dirname "$SUBAGENT_MODEL_ROUTING_HOME")"
  git clone "$SUBAGENT_MODEL_ROUTING_REPO_URL" "$SUBAGENT_MODEL_ROUTING_HOME"
fi

install_args=()
[ -n "${SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR:-}" ] && install_args=("$SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR")
"$SUBAGENT_MODEL_ROUTING_HOME/scripts/install.sh" "${install_args[@]}"

echo
if [ "$REGISTER" -eq 1 ]; then echo "Registering detected client plugins:"; else echo "Plugin registration commands:"; fi
for client in claude codex copilot; do
  handle_client "$client"
done

echo
echo "Next steps:"
echo "  1. Authenticate prerequisites: codex login; opencode auth login."
echo "  2. Smoke test one shim: printf 'Reply with exactly: pong\\n' | ${SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR:-$HOME/.claude/scripts}/opencode-shim.sh <provider/model> -"
echo "  3. Clone location: $SUBAGENT_MODEL_ROUTING_HOME"
echo "  4. Update later: re-run the one-liner, or git -C $(cmd_text "$SUBAGENT_MODEL_ROUTING_HOME") pull --ff-only"
