#!/usr/bin/env bash
# install.sh - link the shims into ~/.claude/scripts/ (the path the plugin
# packages reference). Pass a different dest dir as $1 to override.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$HOME/.claude/scripts}"
mkdir -p "$DEST"
for s in codex-shim.sh opencode-shim.sh; do
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
echo "Done. Smoke test:"
echo "  printf 'Reply with exactly: pong\n' | $DEST/opencode-shim.sh <provider/model> -"
