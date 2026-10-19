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
| USB, a keyboard or synth plugged into the board | `usb_host.ports()` |
| USB, every MIDI device plugged into the board, merged | `usb_host.all_ports()` |
| A UART (5-pin DIN, TRS, board to board) | `uart.ports(1, tx=17, rx=18)` |
| Windows' MIDI ports (a keyboard, loopMIDI, a DAW) | `windows.ports("loopMIDI")` |
| Linux raw MIDI | `linux.ports("DMK25")` |
| Web MIDI, in a browser page (Pyodide) | `await webmidi.open("DMK25")` |
| Web MIDI, in a Web Worker, relayed by the page | `webmidi.relay_ports(port)` |

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
whole messages, and so does Web MIDI.

A port that polls beside audio should call `readinto` with a buffer of its
own. `read` makes a new `bytes` for every message that arrives, though an
empty poll allocates nothing.

## When each message arrived

Every input port keeps the time each message arrived, so a looper or a
recorder can place notes where they were played, not where your loop got
round to them. Call `midi_in.take_timestamp()` once for each message
`receive()` gives you, whatever its type, clocks included:

```python
import midiports

msg = midi.receive()
if msg is not None:
    when = midi_in.take_timestamp()      # microseconds, or None
    played_ago = midiports.ticks_diff(midiports.ticks_us(), when)
```

Times are whole microseconds: `time.ticks_us()` on MicroPython, which wraps,
so subtract with `midiports.ticks_diff`; `time.monotonic_ns() // 1000` on
CPython and CircuitPython; Web MIDI's own `performance.now()` clock in a
browser. Leave `MIDI`'s `in_channel` at its default and filter on
`msg.channel` yourself, because a message `adafruit_midi` filters out never
reaches you but its time would.

How close a time is depends on the transport:

| Port | Stamped | As fine as |
|---|---|---|
| `usb_device` | in the USB event callback | one USB frame (1 ms at full speed), plus the wait for the scheduled callback |
| Web MIDI | by the browser | the browser's event time |
| `uart`, `linux`, `windows`, `usb_host` | by the read that finds the bytes | how often you poll |

The [package docstring](midiports/__init__.py) has the rules: one time per
message in order, how running status, SysEx and a message split across reads
are stamped, and what happens if you don't take them.

## In a browser

Python running in Pyodide reaches MIDI devices through Web MIDI. The browser
asks the person for permission the first time.

On the page (Pyodide on the main thread, as PyScript runs it), `open` is
awaitable:

```python
from midiports import webmidi

midi_in, midi_out = await webmidi.open("DMK25", sysex=False)
midi = adafruit_midi.MIDI(midi_in=midi_in, midi_out=midi_out)
```

The name matches part of a port's name, ignoring case. Leave it out to merge
every input and send to the first output. A device plugged in later, or
unplugged and plugged back in, joins while the ports are open. If you
already hold a `MIDIAccess`, `webmidi.ports(access, "DMK25")` does the same
without awaiting. Sending SysEx needs `sysex=True`.

Web MIDI doesn't exist in a Web Worker, so a worker gets its MIDI from the
page over a `MessagePort`, and a few lines of JavaScript on the page relay
it. Open the worker's end with `webmidi.relay_ports(port)`. The relay's
messages are plain objects:

| Direction | Message |
|---|---|
| page to worker | `{data: Uint8Array, timeStamp: number}`: one whole MIDI message per post, `timeStamp` from its `MIDIMessageEvent` |
| worker to page | `{data: Uint8Array}`: whole messages to `send()` to the page's output |

Every Web MIDI input keeps the browser's time for each message; see
[When each message arrived](#when-each-message-arrived). The
[module docstring](midiports/webmidi.py) has the details, including which
clock a worker's relayed times are on.

## Limits

- Windows: no SysEx yet. Writing one raises `NotImplementedError` rather than
  dropping it.
- Linux: MicroPython's unix port can list ports but not open them, since its
  `os` has no `open` or `read`. CPython opens them.
- USB: if the host stops reading, messages that don't fit within a few
  milliseconds are dropped and counted in `MIDIPortsInterface.dropped`, so
  your loop never stalls.
- `usb_host` needs `usb.core` (the `usb-core` package) and a firmware with a
  USB host. On an ESP32-P4 with the keyboard behind a hub, call
  `usb.core.start(full_speed=True)` before `ports()`.
- `usb_host.all_ports()` hears every MIDI device on the host at once, and
  ones plugged in later. It never splits one device's message with
  another's, so a long SysEx from one holds the rest until it ends. Writes
  go to every device.
