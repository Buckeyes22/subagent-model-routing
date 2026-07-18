#!/usr/bin/env bash
# bootstrap.sh - clone/update subagent-model-routing, install shims, and print/register plugins.
#
# Env overrides:
#   SUBAGENT_MODEL_ROUTING_HOME        clone location (default: "$HOME/.local/share/subagent-model-routing")
#   SUBAGENT_MODEL_ROUTING_REPO_URL    git source (default: "https://github.com/Buckeyes22/subagent-model-routing")
#   SUBAGENT_MODEL_ROUTING_REF         release tag/branch (default: "v0.6.0")
#   SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR shim install dir passed to install.sh; when unset,
#                             install.sh uses its default "$HOME/.claude/scripts"
set -euo pipefail

REGISTER=0
PROVIDER_MENU=auto
PROVIDER_MENU_REQUESTED=0
PROVIDER_MENU_SKIPPED=0
SUBAGENT_MODEL_ROUTING_REF="${SUBAGENT_MODEL_ROUTING_REF:-v0.6.0}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --register) REGISTER=1 ;;
    --provider-menu) PROVIDER_MENU=always; PROVIDER_MENU_REQUESTED=1 ;;
    --no-provider-menu) PROVIDER_MENU=never; PROVIDER_MENU_SKIPPED=1 ;;
    --ref)
      if [ "$#" -lt 2 ]; then
        echo "error: --ref requires a release tag or branch" >&2
        exit 2
      fi
      SUBAGENT_MODEL_ROUTING_REF="$2"
      shift ;;
    -h|--help)
      echo "Usage: bootstrap.sh [--register] [--provider-menu|--no-provider-menu] [--ref <tag-or-branch>]"
      echo "  --provider-menu     require the optional provider CLI checkbox screen"
      echo "  --no-provider-menu  skip optional provider CLI setup"
      echo "  --ref                install a specific release tag or branch (default: v0.6.0)"
      exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ "$PROVIDER_MENU_REQUESTED" -eq 1 ] && [ "$PROVIDER_MENU_SKIPPED" -eq 1 ]; then
  echo "error: --provider-menu and --no-provider-menu cannot be combined" >&2
  exit 2
fi

if ! command -v git >/dev/null 2>&1; then
  echo "error: git is required but was not found on PATH" >&2
  exit 1
fi

SUBAGENT_MODEL_ROUTING_HOME="${SUBAGENT_MODEL_ROUTING_HOME:-$HOME/.local/share/subagent-model-routing}"
SUBAGENT_MODEL_ROUTING_REPO_URL="${SUBAGENT_MODEL_ROUTING_REPO_URL:-https://github.com/Buckeyes22/subagent-model-routing}"

if [ -z "$SUBAGENT_MODEL_ROUTING_REF" ] || [[ "$SUBAGENT_MODEL_ROUTING_REF" == -* ]] ||
  ! git check-ref-format --allow-onelevel "$SUBAGENT_MODEL_ROUTING_REF" >/dev/null 2>&1; then
  echo "error: invalid release tag or branch: $SUBAGENT_MODEL_ROUTING_REF" >&2
  exit 2
fi

canonical_repo_url() {
  local value="${1%/}"
  value="${value%.git}"
  printf "%s" "$value"
}

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

has_controlling_tty() {
  (exec 9<>/dev/tty && [ -t 9 ]) 2>/dev/null
}

refresh_user_path() {
  local relative candidate prefix=""
  for relative in .local/bin .codex/bin .claude/bin .kimi/bin .opencode/bin .grok/bin; do
    candidate="$HOME/$relative"
    if [ -d "$candidate" ]; then
      case ":$PATH:" in
        *":$candidate:"*) ;;
        *) prefix="${prefix}${prefix:+:}${candidate}" ;;
      esac
    fi
  done
  if [ -n "$prefix" ]; then
    PATH="$prefix:$PATH"
    export PATH
    hash -r
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
  actual_origin="$(git -C "$SUBAGENT_MODEL_ROUTING_HOME" remote get-url origin 2>/dev/null || true)"
  if [ -z "$actual_origin" ] ||
    [ "$(canonical_repo_url "$actual_origin")" != "$(canonical_repo_url "$SUBAGENT_MODEL_ROUTING_REPO_URL")" ]; then
    echo "error: existing clone origin does not match SUBAGENT_MODEL_ROUTING_REPO_URL" >&2
    echo "  expected: $SUBAGENT_MODEL_ROUTING_REPO_URL" >&2
    echo "  actual:   ${actual_origin:-<missing>}" >&2
    exit 1
  fi
  echo "Updating subagent-model-routing at $SUBAGENT_MODEL_ROUTING_HOME to $SUBAGENT_MODEL_ROUTING_REF"
  git -C "$SUBAGENT_MODEL_ROUTING_HOME" fetch --depth 1 origin "$SUBAGENT_MODEL_ROUTING_REF"
  git -C "$SUBAGENT_MODEL_ROUTING_HOME" checkout --detach FETCH_HEAD
else
  echo "Cloning subagent-model-routing $SUBAGENT_MODEL_ROUTING_REF into $SUBAGENT_MODEL_ROUTING_HOME"
  mkdir -p "$(dirname "$SUBAGENT_MODEL_ROUTING_HOME")"
  git clone --depth 1 --single-branch --branch "$SUBAGENT_MODEL_ROUTING_REF" \
    "$SUBAGENT_MODEL_ROUTING_REPO_URL" "$SUBAGENT_MODEL_ROUTING_HOME"
fi
resolved_commit="$(git -C "$SUBAGENT_MODEL_ROUTING_HOME" rev-parse --verify HEAD)"
echo "Using $SUBAGENT_MODEL_ROUTING_REF at commit $resolved_commit"

install_args=()
[ -n "${SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR:-}" ] && install_args=("$SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR")
"$SUBAGENT_MODEL_ROUTING_HOME/scripts/install.sh" "${install_args[@]}"

PROVIDER_SETUP_STATUS=0
SETUP_COMMAND="${SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR:-$HOME/.claude/scripts}/model-routing"
if [ "$PROVIDER_MENU" != never ]; then
  if ! has_controlling_tty; then
    if [ "$PROVIDER_MENU" = always ]; then
      echo "error: --provider-menu requires an interactive terminal (/dev/tty)" >&2
      exit 2
    fi
    echo
    echo "Optional provider CLI setup skipped: no interactive terminal."
    echo "Run later: $(cmd_text "$SETUP_COMMAND" setup providers)"
  elif [ "$PROVIDER_MENU" = auto ] && [ "${TERM:-}" = dumb ]; then
    echo
    echo "Optional provider CLI setup skipped because TERM=dumb."
    echo "Run later: $(cmd_text "$SETUP_COMMAND" setup providers --no-color)"
  else
    echo
    if "$SETUP_COMMAND" setup providers; then
      :
    else
      setup_exit=$?
      case "$setup_exit" in
        1)
          PROVIDER_SETUP_STATUS=1
          echo "warning: one or more selected provider CLIs failed to install; continuing bootstrap" >&2
          ;;
        2)
          if [ "$PROVIDER_MENU" = always ]; then
            exit 2
          fi
          PROVIDER_SETUP_STATUS=1
          echo "warning: optional provider CLI setup could not run; continuing bootstrap" >&2
          ;;
        130|129|143) exit "$setup_exit" ;;
        *)
          PROVIDER_SETUP_STATUS=1
          echo "warning: optional provider CLI setup exited $setup_exit; continuing bootstrap" >&2
          ;;
      esac
    fi
  fi
fi

refresh_user_path

echo
if [ "$REGISTER" -eq 1 ]; then echo "Registering detected client plugins:"; else echo "Plugin registration commands:"; fi
for client in claude codex copilot; do
  handle_client "$client"
done

echo
echo "Next steps:"
echo "  Authenticate installed provider CLIs when ready:"
auth_count=0
for auth_client in codex claude grok kimi opencode; do
  if command -v "$auth_client" >/dev/null 2>&1; then
    auth_count=$((auth_count + 1))
    case "$auth_client" in
      codex) echo "    codex login" ;;
      claude) echo "    claude auth login" ;;
      grok) echo "    grok login (or set XAI_API_KEY for headless use)" ;;
      kimi) echo "    kimi login" ;;
      opencode) echo "    opencode auth login" ;;
    esac
  fi
done
if [ "$auth_count" -eq 0 ]; then
  echo "    No provider CLIs are currently detected."
fi

missing_clients=""
for provider_client in codex claude grok kimi opencode; do
  if ! command -v "$provider_client" >/dev/null 2>&1; then
    missing_clients="${missing_clients}${missing_clients:+, }${provider_client}"
  fi
done
if [ -n "$missing_clients" ]; then
  echo "  Missing provider CLIs: $missing_clients"
  echo "    Install later: $(cmd_text "$SETUP_COMMAND" setup providers)"
fi
shim_dir="${SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR:-$HOME/.claude/scripts}"
if command -v kimi >/dev/null 2>&1; then
  echo "  Smoke test Kimi: printf 'Reply with exactly: pong\\n' | $shim_dir/kimi-shim.sh -"
elif command -v codex >/dev/null 2>&1; then
  echo "  Smoke test Codex: printf 'Reply with exactly: pong\\n' | $shim_dir/codex-shim.sh -"
elif command -v claude >/dev/null 2>&1; then
  echo "  Smoke test Claude: printf 'Reply with exactly: pong\\n' | $shim_dir/claude-shim.sh - --model haiku"
elif command -v grok >/dev/null 2>&1; then
  echo "  Smoke test Grok: printf 'Reply with exactly: pong\\n' | $shim_dir/grok-shim.sh - --effort low"
elif command -v opencode >/dev/null 2>&1; then
  echo "  Smoke test OpenCode: printf 'Reply with exactly: pong\\n' | $shim_dir/opencode-shim.sh <provider/model> -"
else
  echo "  Install and authenticate at least one provider CLI before running a shim smoke test."
fi
echo "  Clone location: $SUBAGENT_MODEL_ROUTING_HOME"
echo "  Diagnose the local installation: ${SUBAGENT_MODEL_ROUTING_SCRIPTS_DIR:-$HOME/.claude/scripts}/model-routing doctor"
echo "  Update later: run the bootstrap script for the desired release tag or branch."

exit "$PROVIDER_SETUP_STATUS"
