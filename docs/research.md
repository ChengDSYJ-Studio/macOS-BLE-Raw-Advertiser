# Related work and contribution

## Public references

| Work | Relevant result | Relationship to this implementation |
| --- | --- | --- |
| [scanbeacon-gem](https://github.com/RadiusNetworks/scanbeacon-gem/blob/f3f9ff9123593ff821b3dba7f253d9735e10082f/ext/core_bluetooth/core_bluetooth.m#L213-L240) | The 2016-12-06 snapshot contains raw advertising through older private IOBluetooth methods | Establishes an earlier Mac raw-advertising implementation using a different API path |
| [InternalBlue on macOS](https://arxiv.org/abs/2005.14606) | Submitted 2020-05-29; studies the macOS stack and undocumented low-level interfaces | Provides related research on Bluetooth experimentation and stack internals |
| [NearDrop issue #91](https://github.com/grishka/NearDrop/issues/91) | 2023–2024 discussion of Service Data restrictions, a local-name encoding approach and older private API behavior | Documents the application need and the API constraint |
| [iOS 26.1 bluetoothd reconstruction](https://github.com/EthanArbuckle/iPhone18-3_26.1_23B85_Restore/blob/90aa0cfe59d9682b4265e1354c8b19ec3c7823ab/usr/sbin/bluetoothd/bluetoothd_89.mm#L4279-L4335) | The 2025-12-07 snapshot contains raw payload keys and a permission test at object offset 191 (`0xBF`) | Publishes the same kind of internal permission structure used as a comparison point here |
| [iOS 18.2 CBPeripheralManager reconstruction](https://github.com/EthanArbuckle/iPhone17-1_18.2_22C152_Restore/blob/e26ed4563f78871c59d2d96856756a65d62517e5/System/Library/Frameworks/CoreBluetooth.framework/CBPeripheralManager.m) | The 2025-08-12 snapshot includes raw payload keys and the privileged-daemon client condition | Documents the client-side branch |
| [Public entitlement record](https://github.com/lechium/iOS14Headers/blob/c0b7e9f0049c6b2571358584eed67c841140624f/entitlements/Daemons/bluetoothd.plist) | Lists `com.apple.BTServer.rawBytesAdvertise` | Establishes prior public documentation of the entitlement name |

Snapshot dates identify the revisions inspected. The reconstructed iOS texts are reverse-engineering outputs, and the Mac profile supplies the build-specific layout used by this implementation.

## Project contribution

This implementation uses hardware breakpoints to capture the target client's raw-advertising request, identifies its session, writes the session permission byte, and submits ADV and SCAN_RSP through the native Bluetooth stack.
Version 1.0 packages that method as a reproducible project: configurable raw payloads, AD validation, a fixed build profile, process-identity checks, debugger-detach confirmation, background lifecycle controls, offline tests, a build script and a release packager.

The concrete artifact is an inspectable implementation and its verification record. Related raw-advertising interfaces, key names and permission structures have the earlier public references above.
