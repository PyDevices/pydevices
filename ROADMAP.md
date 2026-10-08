# Roadmap

pydevices is heading toward covering more of the hardware a board can carry,
with each kind of peripheral described honestly by its role.

## Audio

- A board role for encoded audio. Chips such as the VS1053 decode MP3, Ogg or
  MIDI themselves and encode from a mic, so they get a role of their own
  beside `pcm_out` and `pcm_in` instead of passing as PCM.

## MIDI

- `mididev`, one home for MIDI: the port contract, one MIDI 1.0 parser and the
  desktop OS ports live here, and USB and BLE MIDI become transports that add
  their ports to it.

## BLE

- A measurement of how much BLE slows Wi-Fi on the ESP32-S3, to sit beside the
  measured other direction in [docs/bledev-internals.md](docs/bledev-internals.md).

Bugs, and things you need that don't work yet, go to
[issues](https://github.com/PyDevices/pydevices/issues).
