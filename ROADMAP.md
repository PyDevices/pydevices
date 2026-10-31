# Roadmap

pydevices is heading toward covering more of the hardware a board can carry,
with each kind of peripheral described honestly by its role.

## Audio

- A board role for encoded audio. Chips such as the VS1053 decode MP3, Ogg or
  MIDI themselves and encode from a mic, so they get a role of their own
  beside `pcm_out` and `pcm_in` instead of passing as PCM.
- audiodev on Windows plays through the firmware's C WASAPI speaker when the
  interpreter has it, instead of feeding WASAPI from Python, which cuts about
  50 ms from live input to output.

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

- Announce the device over mDNS, so a phone finds it without typing its address.
- A TouchOSC/OSC codec at the edge, so those controllers can be panels. The
  codec layer is already separate from the transports.

## medialink

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

## Backends

- The backend registry leaves experimental. `backends.register()` and
  `require()` let `AutoDisplay` and `audiodev.auto` pick a backend you wrote;
  their names and calling convention settle before they're called stable.

Bugs, and things you need that don't work yet, go to
[issues](https://github.com/PyDevices/pydevices/issues).
- **`hmilink.appkit`.** An adapter that serves an appkit launcher and its
  apps' models over one transport, the foreground app included, so a phone
  can see and switch apps. hmilink depends on appkit for this, never the
  other way, so an app set that serves no panel loads none of it.

