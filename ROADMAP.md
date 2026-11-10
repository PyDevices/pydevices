# Roadmap

pydevices is heading toward covering more of the hardware a board can carry,
with each kind of peripheral described honestly by its role.

## Installing

- `omip` on CircuitPython brings Adafruit's libraries a package needs, such as
  `asyncio` for `bledev`, so `circup` isn't a second step.
- `omip` and the portable `mip` in `utils/` become one file, once measuring shows
  the browser loaders that use the portable one lose nothing.

## Audio

- A board role for encoded audio. Chips such as the VS1053 decode MP3, Ogg or
  MIDI themselves and encode from a mic, so they get a role of their own
  beside `pcm_out` and `pcm_in` instead of passing as PCM.
- audiodev on Windows plays through the firmware's C WASAPI speaker when the
  interpreter has it, instead of feeding WASAPI from Python, which cuts about
  50 ms from live input to output.
- audiodev on Linux through ALSA directly, from CPython and unix MicroPython,
  so a Raspberry Pi or another Linux board gets low-latency audio without SDL2
  or pygame installed.

## USB

- A USB microphone on the device side, so a board can be a USB mic or a
  full-duplex sound card for a computer or another board.
- `network.USBD_NCM` (Ethernet over USB, MicroPython 1.29): a package for it,
  or a note on turning it on.
- The HID, CDC and MSC host drivers on CircuitPython's own `usb.core` (RP2040,
  i.MX): they lack only `configuration_descriptor()` and the private
  `_release_all()` there. Audio, video and net need the usbhost engine.

## MIDI

- SysEx on Windows in `midiports`: `midiInAddBuffer` and `midiOutLongMsg`, so a
  device's Identity Reply and patch dumps work there as they do on other
  ports. Today input drops SysEx and writing 0xF0 raises.
- DIN MIDI on a Linux serial port in `midiports`, for boards whose MIDI jacks
  are wired to a UART rather than showing up as an ALSA raw MIDI device.

## BLE

- `bledev.hid` reads report descriptors of any length. Today a board reads
  only the first 246 bytes, so a device with a longer map (an Xbox controller's
  is 283) is cut off; the fix is a long GATT read in the firmware.
- A measurement of how much BLE slows Wi-Fi on the ESP32-S3, to sit beside the
  measured other direction in [docs/how-it-works/bledev-internals.md](docs/how-it-works/bledev-internals.md).
- BLE MIDI through Windows MIDI Services' new Bluetooth transport: once it
  ships, a board running `bledev.midi.serve()` should open in any Windows MIDI
  app without pairing, and the BLE docs say so.

## hmilink

- A secret a panel must present before it can read or change the document, and
  encryption on the transports that can carry it, for networks you don't fully
  trust.
- Announce the device over mDNS, so a phone finds it without typing its address.
- `hmilink.appkit`: an appkit launcher and its apps' models served over one
  transport, so a phone can see and switch apps. An app set that serves no
  panel loads none of it.

## medialink

- Private links: peers prove they share a secret and their sound and pictures
  are encrypted, so a link can run on a network you don't fully trust.
- Talk both ways at once on a videophone, on boards whose speaker and
  microphone share one I2S port: that needs a duplex I2S path.
- Decode pictures beside the sound rather than in the same loop, so a
  videophone keeps clean sound with 640x480 pictures both ways.
- One camera watched from several screens at once; today the last watcher
  to connect gets the pictures.
- Show progressive JPEGs on boards, whose firmware decoder reads only
  baseline ones.
- A BLE transport, using ADPCM to fit its bandwidth, for boards with no
  Wi-Fi between them.

## mp4mux

- Fragmented MP4 as an option, so a recording cut off by a power loss still
  plays up to its last fragment instead of needing a repair tool.
- 64-bit chunk offsets, for recordings past 4 GB in one file.

## Backends

- The backend registry leaves experimental. `backends.register()` and
  `require()` let `AutoDisplay` and `audiodev.auto` pick a backend you wrote;
  their names and calling convention settle before they're called stable.

Bugs, and things you need that don't work yet, go to
[issues](https://github.com/PyDevices/pydevices/issues).
