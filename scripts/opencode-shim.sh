#!/usr/bin/env bash
# opencode-shim.sh - compatibility wrapper for the shared Python runtime.
set -u

HERE="$(cd -- "${BASH_SOURCE[0]%/*}" && pwd -P)"
ENTRYPOINT="$HERE/model-routing"

if [ ! -f "$ENTRYPOINT" ]; then
  echo "opencode-shim: shared runtime not found at $ENTRYPOINT" >&2
  echo "SHIM-DONE exit=127"
  exit 127
fi

if PYTHON_BIN="$(command -v python3 2>/dev/null)"; then
  :
elif [ -x /usr/bin/python3 ]; then
  PYTHON_BIN=/usr/bin/python3
else
  echo "opencode-shim: Python 3.11 or newer is required" >&2
  echo "SHIM-DONE exit=127"
  exit 127
fi

exec "$PYTHON_BIN" "$ENTRYPOINT" _shim opencode "$@"
