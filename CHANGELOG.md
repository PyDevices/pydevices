## v0.7.7rc1 (2026-10-21)

- Experimental: `backends`, a small registry that `AutoDisplay` and `audiodev.auto` now look their backend up in. `backends.register("display", name, "module:Class", probe=...)` adds one and `backends.require(kind, name)` asks for it from a `board_config.py`. The search order is the `PYDEVICES_DISPLAY` / `PYDEVICES_AUDIO` environment variable, then what the config required, then the built-in host backends in the order they were tried before; a backend you register is never picked unless it was required or named. `AutoDisplay` passes extra keyword arguments to the backend that wins. What `auto` picks on each host is unchanged. See [docs/displaydev.md](docs/displaydev.md#experimental-your-own-backend)
- Every board config and every driver is a package of the library index, named by its folder or module. A board's `manifest.py` requires the driver packages it uses, and mip installs them as `deps` from the same index, so a driver fixed once reaches every board. Drivers are listed in `drivers/drivers.toml`. Boards with a `tested.json` (written by `tools/mark_tested.py` after the smoke test passes) publish to the main index with their drivers; the rest are in the index's `untested/` folder. [CONTRIBUTING.md](CONTRIBUTING.md) says how to add one
- Each board's `package.json` (its GitHub installer) is now written from its `manifest.py` by `python tools/libbuild.py installers`; `tools/libbuild.py check` is the shape check CI runs on a board or driver change
- **Breaking change:** `drivers/storage/sdcard.py` and `drivers/imu/bmi270.py` are gone; boards require micropython-lib's `sdcard` and `bmi270` packages instead (`mip.install("sdcard")` first on stock MicroPython). The nRF52 keeps its fix as `sdcard_nrf`. `drivers/display/ssd1306.py` is now `ssd1306_bus.py` (`from ssd1306_bus import SSD1306`), so it can't shadow micropython-lib's `ssd1306`
- `pydevices-desktop` from the index no longer carries the desktop board config; the `desktop` board package does, and depends on it. Before, a desktop board package for another host (`pgdisplay`, `windisplay`) could end up with the generic `board_config`
- The M5Stack Tab5 display init tables (`tab5_ili9881c_init.py`, `tab5_st7123_init.py`) parse again: their bytes had lost their quotes
- palettes, pdwidgets and appkit live here now, each in its own folder with its own version, tests and docs. palettes and pdwidgets keep their PyPI names (`pydevices-palettes`, `pydevices-pdwidgets`) and version numbers, and release from this repository with tags named `palettes-vX.Y.Z` and `pdwidgets-vX.Y.Z`
- **Breaking change** (pydevices is under 1.0, so it lands without waiting for 2.0): `usb.host.hid` returns key presses, mouse buttons and movement as events named the way `adafruit_hid` names them, and no longer returns raw reports. In 0.7.6, `Device.read()` returned the report's bytes (a keyboard's modifier byte, a reserved byte, then the keys held); it now returns `None` or a tuple: `(KEY_DOWN, keycode, modifiers)`, `(KEY_UP, ...)`, `(CONSUMER_DOWN, code, 0)`, `(CONSUMER_UP, ...)`, or `(MOUSE_EVENT, buttons, dx, dy, wheel)`. Code that unpacked report bytes has to change; there is no switch to get the bytes back. `Device(dev, KEYBOARD)` and `Device.match()` work as before. See [docs/usb.md](docs/usb.md).
- usb-host-hid: new `usb.host.hid_codes` with `Keycode`, `ConsumerControlCode` and `Mouse`'s button names, at `adafruit_hid`'s values, so nothing needs `adafruit_hid` installed
- usb-host-hid: `Device(..., boot=False)` reads the report descriptor, so media keys, 12 and 16-bit mouse movement and report IDs decode; `interface=` picks a particular HID interface

- audiodev pump: `BusioDriver(volume=85)` holds. When the pump took the codec live, the transport wrote its own volume over the driver's, so a driver built for 85% played at 100% (the ES8311's REG32 read 0xBF, not 0xB0). The driver's volume now becomes the transport's, and a driver built with no `volume=` takes the one its transport is holding
- es8311: `enable_output(False)` also powers the DAC down (REG12), so the DEV-KIT's jack no longer pops when a stream starts. A DAC left powered with no MCLK sat at a third output level, and the clock starting was a 30-40 mV step; powered down, it joins the clocked level without one. The first start after a reset that interrupted playback still pops once
- bledev declares no dependency on aioble; releases also ask the library index to rebuild (#261)
- Tested: the P4 panel and the S3 LCD-4.3 pass their smoke tests (#260)
- Tested: the LILYGO T-Watch S3 passes its smoke test
- The board smoke test never calls a role that would put the board to sleep or reset it (`sleep`, `reset`, and the like); it only checks the role is there. On the T-Watch S3 a `sleep` check used to leave the board in light sleep
- Tested: the ESP32-P4 WIFI6 DEV-KIT with the KeDei 5-inch display passes its smoke test (#259)
- backends: a registry AutoDisplay and audiodev.auto look their backend up in (experimental) (#258)
- Tested: the S3 LCD-7 and the desktop board config pass their smoke tests (#257)
- Board configs and drivers become packages of the library index (#255)

## v0.7.7.dev1 (2026-10-20)

- midiports.usb_host: an empty poll neither raises nor waits, and keeps its transfer
- ROADMAP: host-side keyboards and mice through usb-host-hid
- bledev.hid: reports from different functions come out in the order they were sent

## v0.7.6 (2026-10-19)

- Workflows: publishing-v14, whose publisher publishes top-level packages (midiports, usb-*) to MIP
- device-matrix: the P4 4B and the T-Embed list audio_in_power
- Boards: audio_in_power brings the ES7210 up for audioi2sin.I2SIn on the P4 panel and the T-Embed
- mip-split.toml: midiports and the usb-* packages publish to the MIP index by name (#226)
- test_hostloop: the crashed-script test watches whether the loop is entered, not a 5 ms timer (#227)
- The ecosystem map says where usbif, audioif, cameraif and displayif went

## v0.7.6.dev1 (2026-10-19)

- midiports: usb_device needs usb-device-midi 0.1.1 or later
- The HID and MIDI gate scripts over USB: hid_script typed through usb_hid, and an adafruit_midi echo
- The USB packages move in beside midiports, from usbif (e900c94)
- midiports: usb_host.all_ports() hears every MIDI device at once, merged a whole message at a time, and writes to all
- P4 board packages ship camera_sensors.py and imx219.py, which their camera() imports
- docs/audio: capability.wire's live example is audiodsp's pump
- midiports: usbif_shim goes; usb_host is the hosted-MIDI port, and the tests that leaned on the shim use it
- camera_sensors: board camera() finds Python-described sensors too
- drivers/camera/imx219.py: the Raspberry Pi Camera v2 as data for cameraif
- midiports.usb_host: a MIDI device on the board's USB host port, over usb.core
- pydevices-desktop.toml: regenerated for bledev.hid_gamepad
- bledev.hid on CircuitPython: each report goes out once
- bledev.hid: a paired computer lists the board under its HID name
- bledev.hid: a send's timestamp works on CircuitPython; the keyboard rig differs only in its port line
- Docs: bledev's MIDI and HID on adafruit_midi and adafruit_hid; no BLE on the CircuitPython P4
- HID rig: 30 ms between steps, and the LED report checked through get_last_received_report
- bledev.midi: reads hand out whole messages; the gate rig goes through adafruit_midi
- bledev.hid: devices in usb_hid's shape, for adafruit_hid; a mouse; the old sugar goes
- bledev.midi: Port presents the midiports contract, not usbif's MidiPort
- midiports.windows: available() skips a device that leaves while it lists
- midiports: real-time bytes inside a SysEx come out as their own messages over USB and usbif
- midiports: an arrival time for every incoming message, on every input port
- midiports: Web MIDI ports for Pyodide, on the page and relayed to a worker
- uwin32: MIDI port names decode on MicroPython too
- midiports: any() on input ports, for a poll loop beside audio
- midiports: MIDI ports for adafruit_midi over USB device, UART, Windows and Linux

## v0.7.5 (2026-10-16)


## v0.7.5.dev4 (2026-10-15)

- win_audio: write_now() writes one block straight to the WASAPI device (#218)
- WinDisplay: open maximised, the panel exactly the window's client area (#217)
- WinDisplay: measure and draw in real pixels on a scaled display (#216)

## v0.7.5.dev3 (2026-10-15)

- web input: Caps Lock reaches LVGL text fields (#214)

## v0.7.5.dev2 (2026-10-15)

- display_driver: let LVGL hover with a mouse (#212)

## v0.7.5.dev1 (2026-10-15)

- displaydev: one-call canvas blits, and WorkerDisplay for Python in a Web Worker (#207)
- audiodev.worklet_audio: AudioWorklet output for Python in a Pyodide Web Worker (#209)
- web_audio: convert each write's PCM16 to float in one JS call, not sample by sample in Python (#206)
- T-Watch S3: switch off unused power rails, power the radio, amplifier and haptic driver only while used, and wake on USB (#202)
- Roadmap: MIDI follows adafruit_midi's API over any transport; bledev's MIDI and HID ends meet Adafruit's (#205)
- mdns moves to pydevices-desktop: CircuitPython's mdns API over python-zeroconf (#204)
- audiodev: play a VorbisDecoder through the pump's prefetcher, as an MP3 (#203)
- multimer: Ctrl-C after a long timer callback ends the program; no stray tracebacks (#201)
- sys.exit() or Ctrl-C from a timer callback now ends the program every time (#200)
- Fix an intermittent multimer test failure when the machine is short of CPU (#199)
- test_multimer: count the pending source's post-stall burst against the elapsed grid (#198)
- appdev: App.on_quit() adds a callback to run at quit, without replacing before_quit or another one (#197)

## v0.7.4 (2026-10-12)

- appdev: revert switchable apps (App.scope, AppScope, appdev.launcher); they're likely to return as a package built on appdev rather than inside it (#194)
- test_audiodev: drive the I2S byte-clock with a fake clock (#193)
- docs: link the repo files the prose names (#192)
- mdns: find services on the network, with CircuitPython's mdns API (#191)

## v0.7.3 (2026-10-11)

- Roadmap: BLE MIDI through Windows MIDI Services' Bluetooth transport (#189)
- multimer: recover a timer fire whose callback a full schedule queue dropped (#188)

## v0.7.2 (2026-10-11)

- wifi_manager installs with the pydevices package: fix the install lines (#186)
- wifi_manager joins pydevices: tests and a doc for apps that need the network, work without it, or use it only for maintenance (#185)
- multimer: Ctrl-C inside a timer delivery no longer stops every timer (#183)
- display_driver: a Ctrl-C in an LVGL pass can't stop LVGL (#182)

## v0.7.1 (2026-10-10)

- board-bringup: copy wifi.py only when the firmware doesn't freeze pydevices (#180)
- board-bringup: select a board config's version with version=; drop the github:PyDevices/pydevices install that has no package.json (#179)
- bledev docs: on CircuitPython, copy the files by hand (closes #92) (#178)
- CI: run multimer's nrf interrupt probe on MicroPython in the pump job (#177)
- multimer: on nrf, keep timer deliveries out of the interrupt (#176)
- appdev.launcher on an ESP32: restart from a callback, cap the heap probe, fewer collections (#175)
- multimer: on nrf, put off a timer delivery that lands deep in the stack (#174)
- DEV-KIT: document which H3 position gives the USB hub (the end labelled DEVICE) (#172)
- Seeed Round Display: correct the CHSC6X's x scale (#171)
- appdev.launcher: switch apps by name in-process, restart into the next app when the heap runs low (#170)
- appdev: App.scope() and AppScope, so an app can be closed and its memory given back (#169)
- T-Watch S3: touch mapping, charger, step counter and gestures, RTC alarm, NEC IR, SX1262 LoRa, PDM microphone and sleep (#168)
- LILYGO T-Watch S3 board configs (MicroPython and CircuitPython), and drivers for its AXP2101, BMA423 and DRV2605 (#167)
- Seeed Round Display on the XIAO nRF52840: MicroPython and CircuitPython board configs (#163)
- bledev: a CircuitPython nRF52840 central reaches a MicroPython ESP32 peripheral (#91) (#162)
- multimer: run on the nrf port's machine.Timer (#159)
- test_contract_proof: the Touch-LCD-4B now lists boot_button (#165)
- BOOT is always boot_button: the P4 panel and DEV-KIT display configs stop putting it in keypad (#164)
- Board peripherals contract: CircuitPython configs may have board_peripherals.py; CircuitPython's audio_out/audio_in; audio_power and boot_button; DEV-KIT's lan role is now ethernet (#161)
- display_driver: a flush always ends, so Ctrl-C or soft_reset can't wedge the board (#158)
- AndroidSDLDisplay: let the Activity finish turning before creating the window (#157)
- OLEDs: page drivers for SH1106, SH1107, SSD1305 and 4-bit drivers for SSD1322, SSD1325, SSD1327 (#155)
- DEV-KIT on CircuitPython: a camera() role on the board I2C (#154)
- P4 boards record while they play: pcm_in reads the audio pump's RX half (#153)
- ESP32-P4 DEV-KIT on CircuitPython: board peripherals, and the KeDei display (#152)
- DEV-KIT KeDei config: the BOOT button is a key (#151)
- DEV-KIT board peripherals: the headphone jack is differential (#150)
- ES8311: 100% volume is 0 dB; the DEV-KIT's board peripherals (#149)
- CircuitPython board config for the Waveshare ESP32-S3-Touch-LCD-7; FBDisplay leaves a composited framebuffer to its display (#148)
- Board packages ship the drivers their configs import (#147)
- audiodev: pending PCM in chunks, so a long write never needs a megabyte block (#145)
- CircuitPython board_peripherals for a QT Py ESP32 Pico + Audio BFF; docs list the headless configs (#146)
- SSD1306: a one-bit page driver that runs on CircuitPython, MicroPython and CPython (#143)
- ROADMAP: long report descriptors for bledev.hid (#142)
- 2.4" TFT FeatherWing (CircuitPython): touch CS on D6, no display reset (#141)

## v0.7.0 (2026-10-08)

**Breaking:** the environment helpers live in `boarddev` now. Change `from displaydev import env_get` (and `env_int`, `env_float`, `env_bool`, `env_set`) to `from boarddev import ...`; `displaydev` no longer has them, so the old import raises ImportError (#131).

- docs/lvgl.md: Using LVGL with PyDevices moves here from lvgl-bindings (#132)
- The env helpers move from displaydev to boarddev (a hard break) (#131)
- Board config: Adafruit 3.5" TFT FeatherWing (HX8357D) (#139)
- Roadmap: MIDI moves to mididev (#136)
- audiodev.pump: CPython takes the ServiceDriver path too, now that the CPython wheel has audiopump (#135)
- Comments: reword notes for users (#134)
- Add ROADMAP.md for planned work, and make public text stand on its own (#133)
- displaydev: frames per second and PYDEVICES_REFRESH_MS; display_driver moves here (#129)
- WinDisplay refits its scale after a rotation (#130)
- Windows: examples stay up on micropython.exe, and the numpad types (#128)
- wifi: CircuitPython's wifi.radio API on network.WLAN (#127)
- Release PRs from publishing-v13: the description says what the PR changes and what merging does

## v0.6.7rc1 (2026-10-07)

- pngio.py: MicroPython's pngio, on CPython over Pillow (#125)

## v0.6.6 (2026-10-06)

- Board config: the P4 DEV-KIT with a KeDei 5" DSI display; ft6x36 no longer reads an idle 0xFF status as 15 touches (#123)
- wt32sc01-plus: pins from the datasheet, freq=, and a 10 MHz bus (#122)
- board-bringup: images built with build_mp.py, and why a mip-installed pydevices doesn't run on an all image (#120)
- board_configs/desktop gets a freeze manifest; manifest-desktop.py goes (#121)
- manifest.py is a micropython-lib package manifest: freeze it or require() it (#119)
- wifi: connected means a link, not just an address (#117)

## v0.6.5 (2026-09-27)

- multimer: the machine source never re-inits its timer while it could be firing (drum machine panic on the P4) (#115)

## v0.6.4 (2026-09-27)

- FunHouse board package works on stock MicroPython; board_peripherals import order on seven boards; MADCTL rotation on RGB panels (#112)
- android.py: accept a device adb lists as "(no serial number)" (#113)
- docs: the Android launcher and drum machine visual pass, run on the S21 (#111)

## v0.6.3 (2026-09-26)

- ci: every reusable call moves from publishing-v11 to publishing-v12 (#108)
- P4 panel: refuse the second direction on I2S(0) instead of losing the first (#109)

## v0.6.2 (2026-09-26)

- multimer: python -c is a batch entry; the timing ledger's follow-ups (#106)

## v0.6.1 (2026-09-26)

- mip-split: list the new multimer host-only modules; test every listed name exists (#104)

## v0.6.0 (2026-09-26)

- multimer: one Timer, one dispatcher, one wake source per host (the timing redesign) (#101)
- board-bringup: keep secrets.py outside any repository

## v0.5.5 (2026-09-26)

- audiodev: wait for the pump's first block without starving it (#98)
- bledev.hidreport: mice produce events; one keyboard table in keys.py (#97)
- LCD-7: declare EXIO5 low in the CH422G constructor, so board_config leaves native USB connected (#77)
- LCD-7: 14 MHz pixel clock and 10-row bounce buffers, so Wi-Fi and USB survive the panel (#96)

## v0.5.4 (2026-09-25)

- docs: cpble measurements, the file service's conditions, the 2 s GATT wait
- cpble: discover one service when asked, 30 ms interval by default, slow-setup hint, sticky scan names, order across characteristics; board scripts and docs
- cpfiles gate: plant in the read path, unpair on failure; docs: cpble, the CircuitPython PacketBuffer draft
- bledev: run the contract and codec checks on CircuitPython's own interpreter; nus_client runs on CircuitPython
- bledev.cpble: the CircuitPython backend over _bleio
- tests/bledev_board: UART rigs for the P4 HID gate, connect counts and a typed passkey
- bledev.mpble: a board as central types in the passkey even when the stack never asks
- docs: the board-to-board pairing gate, T-Embed to LCD-7
- bledev.repl: the GAP name is the advertised name
- docs: pairing counts from the run log
- docs: pairing and bonding, how it gets there, and what it measured
- bledev.security: draw and clear the passkey in both buffers of a double-buffered panel
- bledev pairing: python -m bledev.bleak pair NAME; honest stale-bond message; tighter gate
- bledev pairing: fixes from the LCD-7 and Windows
- bledev: pairing and bonding for the REPL and file services
- docs/bledev-internals: count every P4-host run
- docs/bledev-internals: the HID gate's numbers, board to board and from the laptop
- bledev.hid board gate: pacing, connection interval and security logging; notification burst scripts (pydevices#87)
- docs: bledev.filetransfer, how it gets there, and what it measured
- pydevices-desktop.toml: ship bledev.filetransfer
- bledev.filetransfer: CircuitPython's BLE file-transfer protocol, board and client
- bledev.midi: the board-to-board gate and latency rig, and what they measured
- bledev.midi: BLE-MIDI as a usbif-style MIDI port, with a portable codec
- docs/bledev-internals: the fast-reconnect failure and what fixed it
- bledev: retry a connection that drops during setup
- bledev: the laptop checks a board's HID side under a vendor UUID; bless probed; two mpble MTU fixes
- bledev.repl: long output arrives intact, and no longer panics the board
- bledev.hid: board gate scripts, the bless probe, and the docs
- bledev.hid: HID over GATT both ways, and a portable report-descriptor parser
- docs/bledev-internals: correct the stall counts and the Windows row
- webble: discovery timeout floor, browser gate test, docs and measurements
- bledev: board configs hand out a bledev adapter; the laptop and coexistence runs
- webble: filter the chooser by service, retry failed connects; gate reports stalls
- bledev: the bleak backend, the BLE REPL and Improv Wi-Fi setup
- bledev.webble: the Web Bluetooth backend, with a browser gate for three runtimes
- docs/bledev: add the final-code gate run to the measurements
- docs: bledev.md for apps, bledev-internals.md for backend authors
- mip-split.toml: bledev publishes to MIP on its own, requiring aioble
- bledev: board-to-board checks, and three mpble fixes they found
- bledev.mpble: the MicroPython backend, over aioble
- bledev: the contract, the fake loopback, nus and auto
- ecosystem.md: regenerated after the site audit (PyDevices.github.io#6)
- docs/android.md: Runner 0.2.2 carries the audio libraries, so the drum machine needs no --deps (#74)
- Freeze manifests an app can include for a standalone build (#75) (#76)
- docs/android.md: download android.py from GitHub instead of cloning pydevices (#73)

## v0.5.3 (2026-09-24)

- android.py: --deps fetches a missing package from the MIP index, or fails before staging (#71)
- psdisplay: a mouse click lands where you click when the page shrinks the canvas (#69)
- android.py: stage multi-file examples and pure-Python deps; --install-apk stops after installing (#68)
- android.py: -c works with Windows adb from WSL (#67)

## v0.5.2 (2026-09-24)

- Android: stop the SDLDisplay flicker; android.py fixes from the phone session (#65)

## v0.5.1 (2026-09-24)

- appdev: micropython.exe can read its own command line (no utf-16-le codec there) (#63)
- Four I2S boards hand audiodev the wire and a power hook, so the pump takes them (#62)
- Board contract: hand a driver the bus, not its pins (#61)
- docs: add pydevices newcomer guide (#60)
- spibus: drop @micropython.native from send(), which delivered nothing on 1.29; cut the per-transfer overhead
- board-bringup: usbif's Python half is frozen with its C half, not installed
- docs: ecosystem map regenerated without cmods
- The stamper and the installer no longer live in cmods
- pydevices#52: a pump that finished before the player looked keeps its audio
- ci: every reusable call moves from publishing-v10 to publishing-v11 (#59)

## v0.5.0 (2026-09-22)

- **The DSP repository is `audiodsp` now** (renamed 2026-09-21), and everything
  here that named it follows. One thing you can notice: on CPython,
  `audiodev.accel` looks for the core's extension under its new name,
  `_audiodsp`, which arrives with the core's first release under its new name. With an older core
  installed the C remix is not found and `audiodev` falls back to the Python
  one — slower, same bytes. `_audioif` in `audiodev/pump.py` is a different
  module, the pump's platform driver, and keeps its name.

`audiodev` plays through the audio pump, and on a board it goes through
`audiobusio.I2SOut`.

**Nothing changes for you.** `audio_out(...)` still hands back an `AudioOut`,
`play(sample)` still plays it, `pcm_out(...)` still hands back a `PCMOutput`
you `write()` to. On a firmware without the pump every byte is the one the
old path produced.

- **`AudioOut` hands the graph to the pump where the firmware carries one.**
  A C thread the interpreter is not on pulls every block — a pinned FreeRTOS
  task on esp32, a `pthread` on a desktop — so your tick stops being what
  keeps the sound alive. Nothing asks for it and no board config opts in. A
  RawSample, a RawSample through an Overdrive, a Synthesizer and a WaveFile
  give the same digest on the old path, on the pump, and on a build with no
  `audiopump` at all: `e0c42e66584d6178`, `26e5bd8c0e8fc086`,
  `50ed7cc0ffce8279`, `aac53cd39e17dbdd`.
- **`lib/audiodev/pump.py` is new** — one module-level `Pump` reached through
  `pump.owner()`, three drivers (`BusioDriver` on esp32, `RingDriver` on unix,
  `ServiceDriver` where there are no threads), `Prefetch` for file-backed
  samples, and `attach_stream()` for raw PCM beside whatever is sounding. One
  client is the pump's tail directly; a second gets a root `audiomixer.Mixer`,
  a voice each at level 1.0, and a retarget. The mixer **sums**, so two loud
  clients clip. `loop` belongs to the client and travels with every swap.
- **On a board there is one way this firmware plays a sample:**
  `AudioOut → Pump → BusioDriver → audiobusio.I2SOut`. `audiodev`'s ESP32
  backend opens no channel, names no DMA size and never touches
  `machine.I2S`. That closes a defect by deletion: it used to open with
  `dma_frame=128` **fixed at every rate**, 16 ms of descriptor at 8 kHz
  against 2.7 ms at 48 kHz, and `I2SOut` sizes it `rate / 200`. What stays
  here is the policy — codec rails and volume, the root mixer, `Prefetch`,
  and the fault sentence.
- **A scheduled tick cannot land in the middle of a rearrangement.** On esp32
  a service tick arrives through `micropython.schedule`, between the
  interpreter's own bytecodes; landing one inside `stop()` finds a player
  that reads like a healthy old-path player and opens `machine.I2S` on the
  port the pump has just released — the drum machine's kit change falling off
  the audio clock with "Peripheral in use". Two guards, both live: a
  per-player `_pumping` flag across `play()` and `stop()`, and a pump-level
  latch around the global rearrangement. Proved by injecting a service tick at
  **every one of the 427 lines of a `play()`**, and at every line of `stop`,
  `close`, `pause` and `attach_stream`.
- **The desktop pump gives the interpreter its time back.** The engine's
  output ring makes the pump wait instead of dropping a block, so the driver
  has stopped parking it. On the **desktop unix build**, with an app doing
  3.5 ms of work a tick: **52 ms per 10 s on audio against 862 ms on the old
  path**, where the parked pump cost 923. With no app work the two are level
  (758 against 713). A live event lands **32.0 ms** later as a ceiling —
  exactly the ring depth — where the parked pump averaged 26.7 ms and spread
  to 69. A WAV plays back byte-identically 10 times out of 10 with all eight
  cores busy, overflow 0 by construction; with the drop planted back, 0 of 10.
  A parked pump used to spin 94 % of a core and now sleeps at 1 %.
- **A fault is a sentence**, not a traceback: `audiodev: the audio pump would
  not start — …`, and playback continues on the old path. A board whose
  config predates `wire=` used to fall back to `machine.I2S` in silence, which
  looks exactly like a working board; it says so once now.
- **`board_peripherals.py` for the Waveshare ESP32-P4 and the LilyGO T-Embed
  S3 publish `wire=` and `audio_power=`** on their PCM devices, so the pump
  can bring the analog path up without opening a stream. On a firmware
  without the pump both are inert. The T-Embed has no codec — `audio_power`
  there raises LilyGO's peripheral rail and, deliberately, lowers nothing,
  because GPIO46 also carries the display and the SD card. Every other I2S
  board keeps the old path and says so once.
- **Tests, where there were none.** `pump.py` had no test in this repository
  at all — CI's only contact with it was a layering rule and a line in a
  manifest. 35 now: 32 in `tests/test_pump.py` against stand-ins and 3 in
  `tests/test_pump_interpreter.py` that drive a real MicroPython build, which
  skip loudly where there is no interpreter (`PYDEVICES_REQUIRE_PUMP=1` turns
  the skip into a failure). Sixteen planted faults, all caught.
- **`.github/workflows/tests.yml` gains a `pump` job** that builds a unix
  MicroPython with `PyDevices/audiodsp` as a user C module and runs the
  interpreter tests against it. It needs audiodsp and nothing else: the
  platform driver is a separate repository and is optional, and without one
  the same loop runs on the interpreter's own thread.
- `lib/audiodev/pump.py` was missing from the generated
  `pydevices-desktop.toml`, which failed the unit suite and the whole
  `validate-pyscript-filesystem-toml` workflow at once — a PyScript desktop
  install fetched every `audiodev` module except the pump. Regenerated with
  the org generator, not hand-edited.

**What has not run on a board.** `audiodev` on `audiobusio` is a desktop
build, a link map, and the sink path it replaced; two ESP32 images are staged
and unflashed. `MP3Decoder` has never been through the pump. Nothing has
measured what a retarget costs. `Pump._retarget()`'s live branch has no test
of its own, and `AudioOut.play`'s latch and `Pump.play`'s `try`/`finally`
survived their planted faults, so they are argued rather than proved.

The **previous** ESP32 backend did run, on the Waveshare ESP32-P4 panel:
`play()` in 8 ms, 100 of 100 stop/play cycles, and `service()` at 95 µs mean
against the old path's 234 µs.

- ci: every reusable call moves from publishing-v6 to publishing-v10 (#57)
- What the pump hands a transport when the app stops draining, measured and pinned
- A transport's priming threshold is part of the interface, and a queue that stops moving is not full
- An interpreter with no provenance stamp says so when the renders disagree
- board-bringup: the five corrections from the P4 sittings
- The golden probe's virtual clock cannot pace a pump on a real thread
- pump.health(): one dict, with the counter nothing read beside the one that is bad news
- Both re-entrancy guards, re-planted where each one is the only thing holding
- The pump does not fail to start; it finishes first, and the guard said the wrong thing
- A probe that opens a real sound device, because every desktop claim so far has been a digest of a file
- Ignore the interpreter provenance stamps beside the binaries
- A fault the pump has been torn down for stops turning players away (#49)
- Declare which lib/ modules cannot run on a microcontroller
- S3 touch boards: CAN is GPIO20/19 and RS485 is GPIO16/15, and RS485 was holding the console pins
- Regenerate the ecosystem map: the pygraphics and palettes descriptions
- Regenerate the ecosystem map: lvgl-python no longer claims macOS wheels
- tests: the pump job checks out audiodsp at v0.5.1, not its default branch (#48)
- The core's distribution is pydevices-audiodsp (#47)
- audioif is audiodsp: links, names and the CPython extension follow the core's rename (#46)
- t-embed: publish wire= and audio_power= so the pump owns I2S(1) (#41) (#44)
- board-bringup: reset after installing, and bring the display up before Wi-Fi (#43)
- audiodev plays through the audio pump, and on a board it goes through audiobusio.I2SOut (#35)
- A board bring-up guide, out of the notes that were written for us
- tests.yml: run the suite when a board's board_config/board_peripherals changes
- t-embed board_peripherals: guard the import-time rail power for host binding
- sdl2_audio: make service() re-entrancy-safe against a scheduled pump
- t-embed: power the peripheral rail from board_peripherals, not only board_config
- Regenerate pydevices-desktop.toml

## v0.4.0 (2026-09-16)

Breaking: the audio roles are renamed, and `audio_in` is removed.

- Audio roles are `pcm_out` (-> `PCMOutput`), `pcm_in` (-> `PCMInput`) and
  `audio_out` (-> `AudioOut`). One name, one return type, on boards and hosts
  alike. Previously `audiodev.auto.audio_out` returned a raw transport while
  `board_peripherals.audio_out` returned a sample player, so callers could not
  know what they held and wrote `getattr(pcm, "transport", pcm)`.
- There is no `audio_in`. Output has a player layer above raw PCM; capture does
  not, so a name implying one was misleading. Use `pcm_in`.
- `audiodev.auto` renames follow: `audio_out` -> `pcm_out`,
  `sample_audio_out` -> `audio_out`. `AutoAudio` is gone. Backend modules
  rename `audio_out`/`audio_in` to `pcm_out`/`pcm_in`; `pwm_tone` exposes
  `tone_out`, because it returns a `ToneOutput`.
- Boards declare an `AudioCapability` and `audiodev.negotiate()` decides,
  replacing each board's hand-written format validation. `channels` (what the
  wire opens) is separate from `native_channels` (what reaches a transducer):
  a mono speaker fed by a two-slot wire needs no mixdown.
- `I2SWire` publishes port and pin numbers on the capability, so a consumer
  that drives the peripheral itself stops reaching into board-private names.
- `adapt_channels`/`ChannelAdapter` convert 1<->2 channels with an injectable
  implementation; `audiodev.accel.best_remix()` supplies the C one where
  audiodsp is present. `audiodev/__init__.py` and every transport import no
  audiodsp, and a test asserts it.
- The portable remix indexes bytes directly instead of calling `struct` per
  sample: 2.9x faster with no allocation. Measured on an ESP32 at 240 MHz, a
  10 ms chunk of 44.1 kHz stereo went from 50.5 ms to 17.3 ms.
- `boarddev.pcm_out`/`pcm_in`/`audio_out` resolve host-vs-board, importing
  `board_peripherals` and never `board_config`.
- `PaceOutput`/`pace_output` and `PCMOutput.try_write` land from the P4 work:
  `machine.I2S` is armed non-blocking, so a raw sink must be paced or
  `write()` raises once DMA fills.
- Every board converted: five I2S boards, five host shims, and the PWM buzzer
  boards (`kind="tone"`, which take no format).
- New `board_configs/nodisplay/` for boards that are only peripherals; first
  occupant is the QT Py ESP32 Pico with an Adafruit Audio BFF.
- ESP32-P4: `audio_power` brings the codec up without opening an I2S stream,
  for a consumer (usbif's C pump) that opens the peripheral itself.

## v0.3.8 (2026-08-29)

- docs: link pass over docs/ and README
- Regenerate the ecosystem map (workbench, micropython-vst3, overlay fixes)
- Adopt publishing-v6 (MIP second-publication race fix)
- sdldisplay: ignore synthetic WINDOWEVENT_CLOSE under headless drivers
- requirements: drop pydevices-usdl2/-uwin32 - registered names with no releases
- Golden probe: prime the output before starting the mixer voice
- Producer script and hardening for interpreter release assets
- Record exec mode on fetch_interpreters.sh and wasm.py
- Regenerate the ecosystem map (audiodsp blurb, micropython-pydevices)
- Distribute interpreter binaries as release assets, not git content
