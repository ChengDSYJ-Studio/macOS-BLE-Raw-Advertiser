#!/bin/bash
# One-shot administrator helper for the current advertising session.
set -euo pipefail
umask 077
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
unset PYTHONPATH PYTHONHOME
RAWBLE_INPUT="$1"
[[ "$EUID" == 0 && -d "$RAWBLE_INPUT" && ! -L "$RAWBLE_INPUT" ]] || exit 2
for RAWBLE_NAME in client.json profile.json session_gate.py; do
    [[ -f "$RAWBLE_INPUT/$RAWBLE_NAME" && ! -L "$RAWBLE_INPUT/$RAWBLE_NAME" ]] || exit 2
done
RAWBLE_OWNER="$(/usr/bin/stat -f %u "$RAWBLE_INPUT")"
[[ "$RAWBLE_OWNER" =~ ^[0-9]+$ && "$RAWBLE_OWNER" != 0 ]] || exit 2
RAWBLE_SECURE="$(/usr/bin/mktemp -d /private/tmp/rawble-root.XXXXXX)"
RAWBLE_RESTORE_DEVTOOLS=0
cleanup() {
    local result="$?"
    set +e
    if [[ "$RAWBLE_RESTORE_DEVTOOLS" == 1 ]]; then
        /usr/sbin/DevToolsSecurity -disable || result=1
    fi
    if [[ -f "$RAWBLE_SECURE/gate.log" ]]; then
        /usr/sbin/chown "$RAWBLE_OWNER" "$RAWBLE_SECURE/gate.log"
        /bin/mv -f "$RAWBLE_SECURE/gate.log" "$RAWBLE_INPUT/gate.log"
    fi
    /bin/rm -rf "$RAWBLE_SECURE"
    exit "$result"
}
trap cleanup EXIT
for RAWBLE_NAME in client.json profile.json session_gate.py; do
    /bin/cp "$RAWBLE_INPUT/$RAWBLE_NAME" "$RAWBLE_SECURE/$RAWBLE_NAME"
    /bin/chmod 600 "$RAWBLE_SECURE/$RAWBLE_NAME"
done
cd "$RAWBLE_SECURE"
if /usr/sbin/DevToolsSecurity -status | /usr/bin/grep -q disabled; then
    RAWBLE_RESTORE_DEVTOOLS=1
    /usr/sbin/DevToolsSecurity -enable
fi
export RAWBLE_STAGE="$RAWBLE_SECURE"
/usr/bin/lldb --no-lldbinit --batch -o 'script import os,sys; sys.dont_write_bytecode=True; sys.path.insert(0,os.environ["RAWBLE_STAGE"]); import session_gate; session_gate.run(lldb.debugger,os.environ["RAWBLE_STAGE"])' > "$RAWBLE_SECURE/gate.log" 2>&1
/usr/bin/grep -q '^RAWBLE_GATE_OK$' "$RAWBLE_SECURE/gate.log"
