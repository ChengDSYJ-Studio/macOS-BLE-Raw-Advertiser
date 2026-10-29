"""Version-pinned LLDB helper. Invoked only after explicit administrator consent.

The payload request is held until both hardware breakpoints are installed.
The permission write is restricted to one matching client's XPC session.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time

try:
    import lldb
except ImportError:
    lldb = None  # Enables importing the memory-policy functions for offline tests.


def read_memory(process, address, count):
    error = lldb.SBError()
    data = process.ReadMemory(address, count, error)
    if not error.Success() or len(data) != count:
        raise RuntimeError("Reading session memory failed: " + str(error))
    return data


def write_memory(process, address, data):
    error = lldb.SBError()
    written = process.WriteMemory(address, data, error)
    if not error.Success() or written != len(data):
        raise RuntimeError("Writing session state failed: " + str(error))


def grant_session(process, session, pid, pid_offset, flag_offset):
    """Return None on PID mismatch; otherwise allow only a 0/1 permission byte."""
    if session <= 0 or pid < 2:
        raise RuntimeError("Invalid session address or PID.")
    actual_pid = int.from_bytes(read_memory(process, session + pid_offset, 4), "little")
    if actual_pid != pid:
        return None
    original = read_memory(process, session + flag_offset, 1)
    if original not in (b"\x00", b"\x01"):
        raise RuntimeError("Unexpected permission byte; expected 0 or 1.")
    write_memory(process, session + flag_offset, b"\x01")
    if read_memory(process, session + flag_offset, 1) != b"\x01":
        raise RuntimeError("Permission readback failed.")
    return {"original": original.hex(), "writtenByteCount": 1,
            "changedByteCount": int(original != b"\x01")}


class BSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved")] + [
        ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
        ("jobc", ctypes.c_uint32), ("tdev", ctypes.c_uint32),
        ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
        ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


def verify_client(context):
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    library.proc_pidpath.restype = ctypes.c_int
    library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                     ctypes.c_void_p, ctypes.c_int]
    library.proc_pidinfo.restype = ctypes.c_int
    buf = ctypes.create_string_buffer(4096)
    info = BSDInfo()
    pid = int(context["pid"])
    n = library.proc_pidpath(pid, buf, len(buf))
    m = library.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if n <= 0 or m != ctypes.sizeof(info):
        raise RuntimeError("Client identity lookup failed; the process may have exited.")
    actual = Path(os.fsdecode(buf.value)).resolve()
    expected = Path(context["executable"]).resolve()
    stamp = f"{info.start_sec}.{info.start_usec}"
    if actual != expected or stamp != context["stamp"] or info.uid != context["uid"]:
        raise RuntimeError("Client path, creation time or user mismatch.")


def atomic_user_file(path, content, uid):
    """Rename a fresh regular file instead of following a destination symlink."""
    descriptor, temporary = tempfile.mkstemp(prefix=".gate-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, 0o600)
        if os.geteuid() == 0:
            os.chown(temporary, uid, -1)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(debugger, stage):
    stage = Path(stage)
    context = json.loads((stage / "client.json").read_text())
    profile = json.loads((stage / "profile.json").read_text())
    runtime = Path(context["root"]) / ".runtime"
    uid = int(context["uid"])
    metadata = runtime.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != uid:
        raise RuntimeError("Runtime directory ownership mismatch.")
    result = {"ok": False, "detached": False, "pid": int(context["pid"]),
              "token": context["token"], "payloadSHA256": context["payloadSHA256"],
              "profile": profile["id"], "systemFilesModified": False,
              "overAirVerified": False}
    target = process = None
    breakpoints = []
    granted = False
    detached = False
    try:
        if os.geteuid() != 0:
            raise RuntimeError("Administrator authorization is required for this session.")
        daemon = profile["daemon"]
        if daemon != "/usr/sbin/bluetoothd":
            raise RuntimeError("Unsupported daemon path.")
        if hashlib.sha256(Path(daemon).read_bytes()).hexdigest() != profile["sha256"]:
            raise RuntimeError("bluetoothd SHA-256 mismatch.")
        verify_client(context)
        target = debugger.CreateTarget(daemon)
        listener = lldb.SBListener("rawble-session-gate")
        error = lldb.SBError()
        process = target.Attach(lldb.SBAttachInfo("bluetoothd", False), error)
        if not error.Success():
            raise RuntimeError("Attaching to bluetoothd failed: " + str(error))
        module = target.FindModule(lldb.SBFileSpec(daemon))
        if not module.IsValid() or (module.GetUUIDString() or "").upper() != profile["moduleUUID"]:
            raise RuntimeError("Loaded module UUID mismatch.")
        addresses = [module.ResolveFileAddress(int(a, 16)).GetLoadAddress(target)
                     for a in profile["gateFileAddresses"]]
        expected = bytes.fromhex(profile["instructionBytes"])
        for address in addresses:
            if read_memory(process, address, len(expected)) != expected:
                raise RuntimeError("Permission-check instruction mismatch.")
            breakpoint = target.BreakpointCreateByAddress(address)
            breakpoints.append(breakpoint)
            hardware = breakpoint.SetIsHardware(True)
            if hardware is not None and not hardware.Success():
                raise RuntimeError("Creating a hardware breakpoint failed.")
            if not breakpoint.IsHardware() or breakpoint.GetNumLocations() != 1:
                raise RuntimeError("Expected one hardware breakpoint location.")
        listener.StartListeningForEvents(process.GetBroadcaster(), lldb.SBProcess.eBroadcastBitStateChanged)
        debugger.SetAsync(True)
        atomic_user_file(runtime / "gate.ready", context["token"].encode(), uid)
        error = process.Continue()
        if not error.Success():
            raise RuntimeError("Resuming bluetoothd failed: " + str(error))
        deadline = time.monotonic() + profile["timeoutSeconds"]
        while time.monotonic() < deadline:
            event = lldb.SBEvent()
            if not listener.WaitForEvent(1, event):
                continue
            process_state = lldb.SBProcess.GetStateFromEvent(event)
            if process_state in (lldb.eStateExited, lldb.eStateDetached):
                raise RuntimeError("bluetoothd exited or detached before the target request.")
            if process_state != lldb.eStateStopped:
                continue
            for thread in process:
                if thread.GetStopReason() != lldb.eStopReasonBreakpoint:
                    continue
                frame = thread.GetFrameAtIndex(0)
                if frame.GetPC() not in addresses:
                    continue
                session = frame.FindRegister(profile["sessionRegister"]).GetValueAsUnsigned()
                # Recheck creation time immediately before a possible permission write.
                verify_client(context)
                outcome = grant_session(process, session, context["pid"],
                                        profile["pidOffset"], profile["flagOffset"])
                if outcome is not None:
                    result.update(outcome)
                    granted = True
                    break
            if granted:
                break
            error = process.Continue()
            if not error.Success():
                raise RuntimeError("Resuming the wait for the target session failed.")
        if not granted:
            raise RuntimeError("Timed out waiting for the target client session.")
    except Exception as error:
        result["error"] = str(error)
    finally:
        if target:
            for breakpoint in breakpoints:
                target.BreakpointDelete(breakpoint.GetID())
        if process and process.IsValid():
            if process.GetState() == lldb.eStateExited:
                result["error"] = "bluetoothd exited during the experiment."
            elif process.GetState() == lldb.eStateDetached:
                detached = True
            else:
                error = process.Detach()
                if not error.Success():
                    process.Continue()
                    error = process.Detach()
                detached = error.Success()
                if not detached:
                    result["error"] = "Debugger detach failed: " + str(error)
        result["detached"] = detached
        result["ok"] = granted and detached and "error" not in result
        result["finishedAt"] = time.time()
        atomic_user_file(runtime / "gate-result.json",
                         json.dumps(result, ensure_ascii=False, indent=2).encode(), uid)
        if target and detached:
            debugger.DeleteTarget(target)
    print("RAWBLE_GATE_OK" if result["ok"] else "RAWBLE_GATE_FAILED", flush=True)
    if "error" in result:
        print(result["error"], flush=True)
    return result["ok"]
