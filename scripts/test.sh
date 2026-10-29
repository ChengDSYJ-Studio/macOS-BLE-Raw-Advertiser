#!/bin/bash
# Runs the offline payload, session policy and archive tests.
set -euo pipefail
RAWBLE_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
RAWBLE_PYTHON="${RAWBLE_PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1
"$RAWBLE_PYTHON" -m unittest discover -s "$RAWBLE_ROOT/tests" -v
for RAWBLE_SCRIPT in "$RAWBLE_ROOT"/*.command "$RAWBLE_ROOT"/scripts/*.sh; do
    /bin/bash -n "$RAWBLE_SCRIPT"
done
