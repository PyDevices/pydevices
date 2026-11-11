# Bluetooth LE support

What `bledev` can do on each host, and what it can't. The
[Bluetooth LE guide](../guides/bluetooth-le.md) shows how to use each part.

## Roles and features by host

| | MicroPython | CircuitPython | Laptop (`bleak`) | Browser (`webble`) |
|---|---|---|---|---|
| Peripheral: advertise, serve a GATT table | Yes | Yes | No | No |
| Central: scan, connect | Yes | Yes | Yes | The browser's chooser stands in for a scan |
| Indications sent by a peripheral | Yes, waits for the acknowledgement | Sent, but the acknowledgement isn't reported | No | No |
| Indications received by a central | Yes | No | Yes | Yes |
| Long reads, past one packet | No | No | Yes | Yes |
| Resolvable private addresses | Yes on NimBLE (the ESP32 family), with `config(addr_mode=)` | No | No | No |
| Pairing | Just Works, passkey, numeric comparison | Just Works only | The operating system's | The browser's |
| Bonding | Yes, kept in NVS or a file | Always | The operating system's | The browser's |
| ATT MTU | Set with `config(mtu=)` | Fixed at build time | Set with `config(mtu=)` | Recorded, not used: the browser never reports it |

## What the parts give you

| Part | What it is | Roles |
|---|---|---|
| `bledev.nus` | Nordic UART: a two-way byte stream | `serve()` on a board, `connect()` from any host |
| `bledev.midi` | BLE-MIDI 1.0 as a MIDI port | `serve()` on a board, `connect()` from anywhere that can be a central |
| `bledev.improv` | Wi-Fi setup with Improv | `serve()` on a board, `provision()` from a laptop or another board |
| `bledev.repl` | The REPL over Bluetooth, behind a password, with optional pairing | `start()` on MicroPython, `connect()` from any central |
| `bledev.filetransfer` | CircuitPython's file transfer service (`0xFEBB`) | `start()` on MicroPython, `connect()` from any central; CircuitPython serves it itself |
| `bledev.battery` | Battery Service (0x180F) | A peripheral: `Battery` |
| `bledev.deviceinfo` | Device Information Service (0x180A) | A peripheral: `DeviceInformation` |
| `bledev.heartrate` | Heart Rate Service (0x180D), with the energy-expended control point | A peripheral: `HeartRate` |
| `bledev.cyclingspeed` | Cycling Speed and Cadence Service (0x1816), with its control point | A peripheral: `CyclingSpeedCadence` |
| `bledev.cyclingpower` | Cycling Power Service (0x1818), with its control point | A peripheral: `CyclingPower` |
| `bledev.runningspeed` | Running Speed and Cadence Service (0x1814), with its control point | A peripheral: `RunningSpeedCadence` |
| `bledev.environmental` | Environmental Sensing Service (0x181A): temperature, humidity, pressure and UV index | A peripheral: `EnvironmentalSensing` |
| `bledev.hid`, host | Keyboards, remotes and gamepads, as PyDevices events | `connect()` from a board or a laptop |
| `bledev.hid`, device | A keyboard, mouse, media remote and gamepad, with `battery` and `deviceinfo` inside it | `Peripheral.serve()` on a board |
| `Service` and `Characteristic` | Your own GATT table, served or discovered | Each host, in the roles above |

## Not supported, and why

| What | Where | Because |
|---|---|---|
| Peripheral role | Laptop, browser | `bleak` has no GATT server, and Web Bluetooth is central only |
| Scanning | Browser | A page can't scan; `find()` opens the browser's device chooser |
| Passkey and numeric comparison | CircuitPython | `_bleio` has no call for them: `authenticated=True` raises `UnsupportedError`, and it always bonds |
| Receiving indications | CircuitPython | Its ESP32 port ignores them |
| Reading a value longer than one packet | MicroPython, CircuitPython | Neither `bluetooth` nor `_bleio` exposes a long read. A device with a report map past 246 bytes is cut off |
| HID over GATT as a host | Laptop, browser | Windows keeps the HID service from apps, and Web Bluetooth's blocklist covers it. A board's HID characteristics are also served under a vendor UUID, so a laptop can inspect them |
| Bluetooth 5 features: extended and periodic advertising, the 2M and Coded PHYs, LE Audio | MicroPython | The `bluetooth` module has no calls for them |
| Resolvable and non-resolvable private addresses | Pico W on MicroPython; CircuitPython; laptop; browser | BTstack has no RPA or NRPA, `_bleio` has no call for them, and a laptop or browser leaves the address to the operating system |
| A BLE radio | ESP32-P4 on CircuitPython | CircuitPython builds no Bluetooth for the P4 |
