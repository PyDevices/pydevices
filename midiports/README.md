# midiports

MIDI ports for Adafruit's [`adafruit_midi`](https://docs.circuitpython.org/projects/midi/en/latest/),
on MicroPython and desktop Python. Your MIDI code is CircuitPython's: the
same `MIDI` object, the same `NoteOn` and `ControlChange` messages. This
package supplies the two ports `MIDI` reads and writes, for each way MIDI
can reach you:

```python
import adafruit_midi
from adafruit_midi.note_on import NoteOn

from midiports import usb_device
midi_in, midi_out = usb_device.ports()        # the board is a USB MIDI device

midi = adafruit_midi.MIDI(midi_in=midi_in, midi_out=midi_out)
midi.send(NoteOn(60, 100))
while True:
    msg = midi.receive()
    if msg is not None:
        print(msg)
```

To use another transport, change the line that opens the ports:

| Transport | The ports line |
|---|---|
| USB, the board as a device | `usb_device.ports()` |
| A UART (5-pin DIN, TRS, board to board) | `uart.ports(1, tx=17, rx=18)` |
| Windows' MIDI ports (a keyboard, loopMIDI, a DAW) | `windows.ports("loopMIDI")` |
| Linux raw MIDI | `linux.ports("DMK25")` |

Import each from `midiports`. BLE MIDI ports come from
[`bledev`](../docs/bledev.md), which moves onto this package's ports next.

## Install

On a board, with `mip`:

```python
import mip
mip.install("github:PyDevices/pydevices/midiports")
```

That fetches `midiports` and Adafruit's `adafruit_midi`, pinned to a release
tag. MIDI over USB also needs micropython-lib's `usb-device-midi` and a
firmware with `machine.USBDevice`. Install it first from MicroPython's own
index, unless your firmware already has it frozen in:

```python
mip.install("usb-device-midi")
```

From a computer, `mpremote mip install github:PyDevices/pydevices/midiports`
does the same.

On desktop Python, the Windows port needs `uwin32` from `pydevices-desktop`.
`midiports` isn't on PyPI yet, so put this folder on your path. Adafruit
publishes `adafruit_midi` there as `adafruit-circuitpython-midi`.

## The ports

The contract is CircuitPython's `usb_midi`. An input port has
`read(nbytes)`, which returns `bytes`, or `None` when nothing has arrived,
and `readinto(buf, nbytes)`. An output port has `write(buf, nbytes)`. None
of them block. The [package docstring](midiports/__init__.py) has the whole
contract.

Input ports hand out whole messages. A 5-pin cable sends running status
(the status byte left off repeated messages) and may put a clock byte in the
middle of a note, and `adafruit_midi` reads neither. So the UART and Linux
ports wrap their input in `midiports.WholeMessages`, which fixes both. Wrap
any other byte stream the same way. USB-MIDI and Windows already deliver
whole messages.

A port that polls beside audio should call `readinto` with a buffer of its
own. `read` makes a new `bytes` for every message that arrives, though an
empty poll allocates nothing.

## Limits

- Windows: no SysEx yet. Writing one raises `NotImplementedError` rather than
  dropping it.
- Linux: MicroPython's unix port can list ports but not open them, since its
  `os` has no `open` or `read`. CPython opens them.
- USB: if the host stops reading, messages that don't fit within a few
  milliseconds are dropped and counted in `MIDIPortsInterface.dropped`, so
  your loop never stalls.
- `usbif_shim` is temporary. It wraps the old `usbif` firmware's MIDI so
  existing apps keep working, and goes once that firmware moves onto
  `machine.USBDevice`.
