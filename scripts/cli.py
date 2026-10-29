#!/usr/bin/env python3
"""Project commands with structured subprocess argument lists."""
import argparse
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from payload import PayloadError, load_config, parse_ad, decode_hex

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profiles/macos-26.4-25E246-arm64.json"
APP = ROOT / "build/RawBLEAdvertiser.app"
EXE = APP / "Contents/MacOS/RawBLEAdvertiser"
RUNTIME = ROOT / ".runtime"


class ProjectError(RuntimeError):
    pass


def atomic_json(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def capture(arguments, **kwargs):
    return subprocess.run([str(a) for a in arguments], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)


def profile():
    value = json.loads(PROFILE_PATH.read_text())
    if value["daemon"] != "/usr/sbin/bluetoothd" or value["architecture"] != "arm64":
        raise ProjectError("Invalid platform profile.")
    if len(bytes.fromhex(value["sha256"])) != 32 or len(bytes.fromhex(value["instructionBytes"])) != 12:
        raise ProjectError("Invalid profile hash or instruction length.")
    if len(value["gateFileAddresses"]) != 2 or any(int(a, 16) % 4 for a in value["gateFileAddresses"]):
        raise ProjectError("Invalid permission-check address format.")
    if value["sessionRegister"] != "x26" or type(value["pidOffset"]) is not int or type(value["flagOffset"]) is not int:
        raise ProjectError("Invalid session layout profile.")
    if not (0 <= value["pidOffset"] < 4096 and 0 <= value["flagOffset"] < 4096 and 1 <= value["timeoutSeconds"] <= 30):
        raise ProjectError("Invalid session offset or timeout.")
    return value


def checks():
    supported = profile()
    output = {"profile": supported["id"], "platform": platform.system(), "checks": []}
    def check(label, ok, detail):
        output["checks"].append({"name": label, "ok": bool(ok), "detail": detail})
    if sys.platform != "darwin":
        check("macOS", False, "Live advertising requires macOS. Offline validation and tests support other development hosts.")
        return output
    arm = capture(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"])
    check("Apple Silicon", arm.stdout.strip() == "1", arm.stdout.strip())
    build = capture(["/usr/bin/sw_vers", "-buildVersion"]).stdout.strip()
    check("macOS build", build == supported["build"], build)
    daemon_hash = hashlib.sha256(Path(supported["daemon"]).read_bytes()).hexdigest()
    check("bluetoothd SHA-256", daemon_hash == supported["sha256"], daemon_hash)
    tools = capture(["/usr/bin/xcrun", "--find", "lldb"])
    check("LLDB", tools.returncode == 0, tools.stdout.strip())
    if EXE.is_file():
        debug = capture([EXE, "--check", ROOT])
        check("SIP debugging", debug.returncode == 0, debug.stdout.strip())
    else:
        check("application built", False, "Run scripts/build.sh to build the application, then check debugging access.")
    return output


def print_checks(value):
    for check in value["checks"]:
        print(("PASS" if check["ok"] else "FAIL") + " | " + check["name"] + ": " + check["detail"])


def ensure_runtime():
    if RUNTIME.is_symlink():
        raise ProjectError(".runtime must be a regular directory.")
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    metadata = RUNTIME.stat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ProjectError("The runtime directory must belong to the current user.")
    RUNTIME.chmod(0o700)


def acquire_control_lock():
    if fcntl is None:
        raise ProjectError("Live advertising requires macOS process controls.")
    ensure_runtime()
    descriptor = os.open(RUNTIME / "control.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise ProjectError("Another start or stop operation is in progress. Wait for it to finish.")
    return descriptor


def status():
    if not EXE.exists():
        return 1, {"phase": "off", "message": "Application build is pending."}
    process = capture([EXE, "--status", ROOT])
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError:
        raise ProjectError("Reading status failed: " + process.stdout)
    return process.returncode, value


def stop():
    if not EXE.exists():
        print("Application build is pending. Advertising is stopped.")
        return 0
    process = capture([EXE, "--stop", ROOT])
    print(process.stdout.strip())
    return process.returncode


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("src/main.m", "src/Info.plist", "VERSION")}


def ensure_build():
    try:
        current = json.loads((ROOT / "build/build-info.json").read_text())
    except (OSError, json.JSONDecodeError):
        current = {}
    if not EXE.is_file() or current.get("sources") != source_hashes():
        result = subprocess.run([str(ROOT / "scripts/build.sh")])
        if result.returncode:
            raise ProjectError("Build failed.")
    verify = capture(["/usr/bin/codesign", "--verify", "--strict", str(APP)])
    if verify.returncode:
        raise ProjectError("Application signature verification failed. Rebuild the application.")


def read_current_state(token):
    try:
        value = json.loads((RUNTIME / "state.json").read_text())
        return value if value.get("token") == token else None
    except (OSError, json.JSONDecodeError):
        return None


def start(config_path):
    if sys.platform != "darwin":
        raise ProjectError("Live advertising requires macOS.")
    payload = load_config(config_path)
    # Validate the current system before administrator authorization.
    machine = checks()
    early = [c for c in machine["checks"] if c["name"] not in ("application built", "SIP debugging")]
    if any(not c["ok"] for c in early):
        print_checks({"checks": early})
        raise ProjectError("Platform validation failed. See the checks above.")
    ensure_build()
    machine = checks()
    if any(not c["ok"] for c in machine["checks"]):
        print_checks(machine)
        raise ProjectError("Environment checks failed. Follow the setup steps in README.")
    code, saved = status()
    if code == 0:
        if saved.get("payloadSHA256") != payload["payloadSHA256"]:
            raise ProjectError("A different payload is running. Stop it before starting the new configuration.")
        print("The same payload is already running.")
        return 0
    if code == 3:
        raise ProjectError("The client is starting. Use status to check its progress.")
    if code == 5:
        if stop():
            raise ProjectError("The previous client is still shutting down.")
    token = str(uuid.uuid4())
    payload["token"] = token
    atomic_json(RUNTIME / "request.json", payload)
    for name in ("gate.ready", "gate-result.json"):
        (RUNTIME / name).unlink(missing_ok=True)
    launched = False
    try:
        opened = capture(["/usr/bin/open", "-g", "-n", APP, "--args", "--run", ROOT, token])
        if opened.returncode:
            raise ProjectError("Launching the application failed: " + opened.stdout)
        launched = True
        print("Preparing the application. Allow RawBLEAdvertiser to use Bluetooth when prompted.", flush=True)
        saved = None
        for _ in range(150):
            saved = read_current_state(token)
            if saved and saved.get("phase") == "waiting":
                break
            if saved and saved.get("phase") in ("error", "off"):
                raise ProjectError(saved.get("message", "Client startup failed."))
            time.sleep(0.2)
        else:
            raise ProjectError("Bluetooth startup timed out after 30 seconds. Check Bluetooth and folder access, and .runtime/advertiser.log.")
        with tempfile.TemporaryDirectory(prefix="rawble-", dir="/private/tmp") as temporary:
            stage = Path(temporary)
            context = {"root": str(ROOT), "pid": saved["pid"], "stamp": saved["stamp"],
                       "uid": os.getuid(), "token": token, "executable": str(EXE.resolve()),
                       "payloadSHA256": payload["payloadSHA256"]}
            atomic_json(stage / "client.json", context)
            atomic_json(stage / "profile.json", profile())
            for name in ("session_gate.py", "gate-root.sh"):
                shutil.copy2(ROOT / "scripts" / name, stage / name)
            print("Authorize this session in the macOS administrator dialog.", flush=True)
            script = '''on run argv
set cmd to "/bin/bash"
repeat with arg in argv
    set cmd to cmd & " " & quoted form of arg
end repeat
do shell script cmd with administrator privileges
end run'''
            try:
                elevated = subprocess.run(["/usr/bin/osascript", "-", str(stage / "gate-root.sh"), str(stage)],
                                          input=script, text=True, timeout=120)
            finally:
                if (stage / "gate.log").is_file():
                    # Publish the log through a fresh file owned by the current user.
                    fd, temporary_log = tempfile.mkstemp(prefix=".log-", dir=str(RUNTIME))
                    with os.fdopen(fd, "wb") as stream:
                        stream.write((stage / "gate.log").read_bytes())
                    os.replace(temporary_log, RUNTIME / "gate.log")
            if elevated.returncode:
                raise ProjectError("Session authorization failed. See .runtime/gate.log.")
        for _ in range(40):
            code, saved = status()
            if code == 0 and saved.get("token") == token:
                print(saved["message"])
                print(f"ADV {payload['advertisingBytes']} bytes / SCAN_RSP {payload['scanResponseBytes']} bytes")
                return 0
            if code != 3:
                raise ProjectError(saved.get("message", "Advertising startup failed."))
            time.sleep(0.2)
        raise ProjectError("Timed out confirming raw advertising.")
    except BaseException:
        if launched:
            stop()
        raise


def parser():
    p = argparse.ArgumentParser(description="macOS BLE Raw Advertiser")
    p.add_argument("action", choices=("start", "stop", "status", "doctor", "validate"))
    p.add_argument("--config", type=Path, help="JSON payload; defaults to config.json, then examples/ibeacon-service-data.json")
    p.add_argument("--json", action="store_true", help="print JSON for status, doctor or validate")
    return p


def main():
    arguments = parser().parse_args()
    descriptor = None
    try:
        config = arguments.config or (ROOT / "config.json" if (ROOT / "config.json").exists()
                                      else ROOT / "examples/ibeacon-service-data.json")
        if arguments.action == "validate":
            value = load_config(config)
            value["advertisingStructures"] = parse_ad(decode_hex(value["advertisingDataHex"], "ADV"))
            value["scanResponseStructures"] = parse_ad(decode_hex(value["scanResponseDataHex"], "SCAN_RSP"), scan_response=True)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0
        if arguments.action == "doctor":
            value = checks()
            if arguments.json:
                print(json.dumps(value, ensure_ascii=False, indent=2))
            else:
                print_checks(value)
            return 0 if all(c["ok"] for c in value["checks"]) else 2
        if arguments.action == "status":
            code, value = status()
            value.pop("token", None)
            value.pop("stamp", None)
            print(json.dumps(value, ensure_ascii=False, indent=2) if arguments.json else value.get("message", "Status unavailable"))
            return code
        descriptor = acquire_control_lock()
        return start(config) if arguments.action == "start" else stop()
    except (ProjectError, PayloadError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Operation cancelled.", file=sys.stderr)
        return 130
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
