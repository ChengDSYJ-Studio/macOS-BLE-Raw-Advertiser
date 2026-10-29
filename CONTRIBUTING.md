# Contributing

Run `./scripts/test.sh` and `./scripts/build.sh` when changing the application or control scripts. The offline tests exercise payload parsing, memory policy and release-file selection.

## Fixes and features

Describe the trigger, observed behavior, resulting behavior and validation. Keep changes focused on a concrete advertising or lifecycle case. Use the public example payloads to make reports reproducible.

## Platform adaptation

A new profile is established through analysis and physical-machine verification:

1. Record the daemon SHA-256, module UUID, permission-check addresses and instruction semantics.
2. Confirm the session register, client PID offset, permission offset and session lifecycle.
3. Exercise PID matching, unexpected permission values, read/write failures and debugger cleanup.
4. Validate startup, background lifetime, shutdown and receiver evidence on a physical machine.
5. Document the profile's supported build and operating requirements.

Provide the minimal relevant disassembly or log excerpts with their source. Keep local runtime state and device-specific configuration in the working copy's ignored directories.

## Issue reports

Useful details include the project version, a reviewed `doctor --json` output, the example or payload fingerprint, the stage of the failure, and a small relevant log excerpt. Check the excerpt's device identifiers, user paths and launch tokens before sharing.

An external capture or scan export strengthens a report about transmitted bytes. State files and callbacks provide the application-side evidence.
