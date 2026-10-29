#!/bin/bash
set -u
RAWBLE_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)" || exit 1
RAWBLE_PYTHON="$(/usr/bin/xcrun --find python3 2>/dev/null)"
if [[ -z "$RAWBLE_PYTHON" ]]; then
    printf 'Apple Command Line Tools are required. Run xcode-select --install in Terminal.\n'
    exit 2
fi
export PYTHONDONTWRITEBYTECODE=1
"$RAWBLE_PYTHON" "$RAWBLE_ROOT/scripts/cli.py" "$@"
RAWBLE_RESULT=$?
if [[ -t 0 && "${RAWBLE_NO_PAUSE:-0}" != 1 ]]; then
    printf '\nPress Return to close this window...'
    read -r RAWBLE_IGNORED
fi
exit "$RAWBLE_RESULT"
