#!/usr/bin/env bash
# install.sh - link the shims into ~/.claude/scripts/ (the path the plugin
# packages reference). Pass a different dest dir as $1 to override.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$HOME/.claude/scripts}"

if PYTHON_BIN="$(command -v python3 2>/dev/null)"; then
  :
elif [ -x /usr/bin/python3 ]; then
  PYTHON_BIN=/usr/bin/python3
else
  echo "error: Python 3.11 or newer is required" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "error: Python 3.11 or newer is required (found: $($PYTHON_BIN --version 2>&1))" >&2
  exit 1
fi

mkdir -p "$DEST"
for s in model-routing codex-shim.sh opencode-shim.sh grok-shim.sh claude-shim.sh kimi-shim.sh; do
  chmod +x "$HERE/$s"
  if [ -L "$DEST/$s" ]; then
    old_target="$(readlink "$DEST/$s")"
    if [ "$old_target" = "$HERE/$s" ]; then
      echo "already linked: $s"
      continue
    fi
    mv "$DEST/$s" "$DEST/$s.bak.$(date +%Y%m%d%H%M%S)"
    echo "backed up existing $s symlink (was -> $old_target)"
  fi
  if [ -e "$DEST/$s" ] && [ ! -L "$DEST/$s" ]; then
    mv "$DEST/$s" "$DEST/$s.bak.$(date +%Y%m%d%H%M%S)"
    echo "backed up existing $s"
  fi
  ln -sfn "$HERE/$s" "$DEST/$s"
  echo "linked $DEST/$s -> $HERE/$s"
done
echo "Running installation doctor:"
SUBAGENT_MODEL_ROUTING_INSTALL_DIR="$DEST" "$DEST/model-routing" doctor --installation-only
echo "Done. Smoke test:"
echo "  $DEST/model-routing doctor"
echo "  $DEST/model-routing runs list"
echo "  printf 'Reply with exactly: pong\n' | $DEST/opencode-shim.sh <provider/model> -"
echo "  printf 'Reply with exactly: pong\n' | $DEST/kimi-shim.sh -"
echo "  printf 'Reply with exactly: pong\n' | $DEST/grok-shim.sh - --effort low"
echo "  printf 'Reply with exactly: pong\n' | $DEST/claude-shim.sh - --model haiku"
