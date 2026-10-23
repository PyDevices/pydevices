# Roadmap

pydevices is heading toward covering more of the hardware a board can carry,
with each kind of peripheral described honestly by its role.

## Audio

- A board role for encoded audio. Chips such as the VS1053 decode MP3, Ogg or
  MIDI themselves and encode from a mic, so they get a role of their own
  beside `pcm_out` and `pcm_in` instead of passing as PCM.

## USB

- A USB microphone on the device side, so a board can be a USB mic or a
  full-duplex sound card for a computer or another board.
- `network.USBD_NCM` (Ethernet over USB, MicroPython 1.29): a package for it,
  or a note on turning it on.
- The HID, CDC and MSC host drivers on CircuitPython's own `usb.core` (RP2040,
  i.MX): they lack only `configuration_descriptor()` and the private
  `_release_all()` there. Audio, video and net need the usbhost engine.

## BLE

- `bledev.hid` reads report descriptors of any length. Today a board reads
  only the first 246 bytes, so a device with a longer map (an Xbox controller's
  is 283) is cut off; the fix is a long GATT read in the firmware.
- A measurement of how much BLE slows Wi-Fi on the ESP32-S3, to sit beside the
  measured other direction in [docs/bledev-internals.md](docs/bledev-internals.md).
- BLE MIDI through Windows MIDI Services' new Bluetooth transport: once it
  ships, a board running `bledev.midi.serve()` should open in any Windows MIDI
  app without pairing, and the BLE docs say so.

## hmilink

- Announce the device over mDNS, so a phone finds it without typing its address.
- A TouchOSC/OSC codec at the edge, so those controllers can be panels. The
  codec layer is already separate from the transports.

Bugs, and things you need that don't work yet, go to
[issues](https://github.com/PyDevices/pydevices/issues).
- **`hmilink.appkit`.** An adapter that serves an appkit launcher and its
  apps' models over one transport, the foreground app included, so a phone
  can see and switch apps. hmilink depends on appkit for this, never the
  other way, so an app set that serves no panel loads none of it.

