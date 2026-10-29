# Architecture

## Request flow

1. `cli.py` loads a JSON configuration. `payload.py` normalizes hex, validates AD structures and the 31-byte capacities, and computes a payload fingerprint.
2. Platform checks confirm the Apple Silicon hardware, macOS build and daemon SHA-256. The application build and system debugging check follow.
3. LaunchServices starts the native application with a unique token. The application validates the buffers again, holds an instance lock and waits for Bluetooth readiness.
4. The application saves its PID, creation timestamp and payload fingerprint, then enters `waiting`.
5. The administrator helper snapshots its inputs into a root-owned temporary directory and starts LLDB with a controlled module search path.
6. LLDB verifies the daemon hash, loaded module UUID and both permission-check instruction windows. It installs hardware breakpoints, publishes `gate.ready`, and resumes the daemon.
7. The app submits `kCBAdvDataRawBytesDataAdvInd`, the configured `kCBAdvDataRawBytesDataScanRsp`, and the private privileged-daemon and connectability options.
8. At a breakpoint, the helper reads the current client's PID from the session object in `x26`. It checks the client's executable path, process creation timestamp and UID, then writes the matching session's permission byte and verifies readback.
9. The helper removes its breakpoints and detaches. It publishes the final authorization and detach result.
10. The app correlates the result with its PID, token and payload fingerprint, then records `on` after the system's advertising callback. A short asynchronous wait handles a callback arriving before the helper's result file.

## Platform profile

The included profile is `macos-26.4-25E246-arm64`.

| Parameter | Value |
| --- | --- |
| Daemon | `/usr/sbin/bluetoothd` |
| Build | `25E246` |
| File SHA-256 | `f5384e7ea60fb2069956481a041b62fa0683769029ff60c150afcc5b6d6ce92f` |
| arm64e UUID | `454D90AC-9404-388D-9927-D6715D280666` |
| Gate file virtual addresses | `0x10060F08C`, `0x10060F158` |
| Instruction bytes | `48ff42391f05007161010054` |
| Client PID offset | `0x28` |
| Permission offset | `0xBF` |

At both gates, the daemon loads `[x26 + 0xBF]`, compares it with `1`, and branches according to the result. LLDB resolves the file virtual addresses against the loaded module to account for ASLR. The profile selects the session layout for this build.

## Permission write

`grant_session` reads the client PID before accessing the permission. A matching session with a permission value of `0` or `1` receives one one-byte write containing `1`.

The result records two separate measures:

- `writtenByteCount`: length of the permission write, `1`.
- `changedByteCount`: `1` when the original value was `0`, or `0` when it was already `1`.

The memory-model tests compare the whole simulated session object before and after the write. The real-system result records the write and readback at the target address. Normal daemon activity and LLDB's debugging state have their own memory effects.

The permission belongs to the client's XPC session. Application shutdown ends that session, and the system reclaims its object. The system debugging configuration persists until the user restores it in Recovery.

## Lifecycle

A control lock serializes start and stop operations in one project directory. The native app holds a second instance lock throughout its lifetime. Stop verifies the saved PID against the executable path and process creation time.

The controller reuses an active session for the same payload fingerprint. Changing the payload requires a new session. A Bluetooth reset after submission ends the current app session and asks the operator to start again.

The helper handles gate timeouts, instruction mismatches, identity changes and memory failures as errors. Cleanup removes breakpoints and detaches, with a resume-and-detach retry when necessary. The final `ok` result requires a successful permission write and confirmed debugger detach.

## Administrator execution

The operating procedure uses administrator authorization and system-process debugging access. LLDB attachment and hardware-breakpoint handling briefly pause the shared Bluetooth daemon.

The administrator helper snapshots its local inputs into a root-owned workspace, clears Python path overrides, and uses LLDB's explicit initialization options. Results are written through fresh files with ownership assigned to the invoking user. DevToolsSecurity is restored to its prior enabled/disabled state on normal helper exit.


## Runtime state

`state.json` holds the current phase, client identity, payload fingerprint and submission status. `gate-result.json` holds the permission-write and debugger-detach result. Tokens correlate these two processes for one launch. `overAirVerified` tracks the separate external-reception verification state.

Files use the project-owned `.runtime/` directory, and the release packager filters runtime data and local configuration from archives.
