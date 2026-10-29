#!/bin/bash
set -euo pipefail
RAWBLE_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
RAWBLE_APP="$RAWBLE_ROOT/build/RawBLEAdvertiser.app"
RAWBLE_PYTHON="$(/usr/bin/xcrun --find python3)"
if [[ -x "$RAWBLE_APP/Contents/MacOS/RawBLEAdvertiser" ]]; then
    set +e
    "$RAWBLE_APP/Contents/MacOS/RawBLEAdvertiser" --status "$RAWBLE_ROOT" >/dev/null
    RAWBLE_STATUS=$?
    set -e
    if [[ "$RAWBLE_STATUS" == 0 || "$RAWBLE_STATUS" == 3 || "$RAWBLE_STATUS" == 5 ]]; then
        printf 'Stop the project client before rebuilding.\n' >&2
        exit 2
    fi
fi
mkdir -p "$RAWBLE_ROOT/build"
RAWBLE_STAGE="$(/usr/bin/mktemp -d "$RAWBLE_ROOT/build/.compile.XXXXXX")"
trap '/bin/rm -rf "$RAWBLE_STAGE"' EXIT
mkdir -p "$RAWBLE_STAGE/RawBLEAdvertiser.app/Contents/MacOS"
/usr/bin/xcrun clang -arch arm64 -Os -Wall -Wextra -fobjc-arc \
    -framework Foundation -framework CoreBluetooth \
    "$RAWBLE_ROOT/src/main.m" -o "$RAWBLE_STAGE/RawBLEAdvertiser.app/Contents/MacOS/RawBLEAdvertiser"
cp "$RAWBLE_ROOT/src/Info.plist" "$RAWBLE_STAGE/RawBLEAdvertiser.app/Contents/Info.plist"
/usr/bin/codesign --force --sign - --timestamp=none "$RAWBLE_STAGE/RawBLEAdvertiser.app"
/usr/bin/codesign --verify --strict "$RAWBLE_STAGE/RawBLEAdvertiser.app"
if [[ -e "$RAWBLE_APP" ]]; then /bin/rm -rf "$RAWBLE_APP"; fi
mv "$RAWBLE_STAGE/RawBLEAdvertiser.app" "$RAWBLE_APP"
"$RAWBLE_PYTHON" - "$RAWBLE_ROOT" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
sources={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('src/main.m','src/Info.plist','VERSION')}
value={'version':(root/'VERSION').read_text().strip(),'architecture':'arm64','sources':sources}
(root/'build/build-info.json').write_text(json.dumps(value,indent=2)+'\n')
PY
printf 'Built: %s\n' "$RAWBLE_APP"
