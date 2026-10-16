# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The gate's messages through Adafruit's ``adafruit_midi``, over a bledev.midi port.

``midi_server.py`` and ``midi_client.py`` both use this for the 1,000-message
gate, so what crosses the air was sent by ``adafruit_midi.MIDI.send()`` and
read back by ``MIDI.receive()``, the way a CircuitPython script does over
``usb_midi``. The rig's raw bytes become ``adafruit_midi`` messages with
Adafruit's own parser, and what arrives is compared as bytes again.
"""

import adafruit_midi
from adafruit_midi.control_change import ControlChange  # noqa: F401 (registers the type)
from adafruit_midi.midi_message import MIDIMessage
from adafruit_midi.note_off import NoteOff  # noqa: F401
from adafruit_midi.note_on import NoteOn  # noqa: F401
from adafruit_midi.pitch_bend import PitchBend  # noqa: F401
from adafruit_midi.program_change import ProgramChange  # noqa: F401
from adafruit_midi.system_exclusive import SystemExclusive  # noqa: F401
from adafruit_midi.timing_clock import TimingClock  # noqa: F401

import bledev

_ALL = tuple(range(16))  # what MIDI(in_channel=None) means; the parser wants it spelled out


class AdafruitIO:
    def __init__(self, port):
        self.port = port
        # Room for the rig's 300-byte SysEx in one piece.
        self.midi = adafruit_midi.MIDI(midi_in=port, midi_out=port, in_buf_size=512)

    def send(self, raw):
        msg, _, _ = MIDIMessage.from_message_bytes(bytearray(raw), _ALL)
        if msg is None:
            raise ValueError("adafruit_midi can't parse {!r}".format(bytes(raw[:4])))
        channel = getattr(msg, "channel", None)
        self.midi.send(msg, channel=channel if channel is not None else 0)

    async def receive(self, timeout_ms):
        """The next message's bytes, as ``adafruit_midi`` parsed it."""
        waited = 0
        while True:
            # receive() also parses what an earlier call buffered, so ask it
            # whenever the port or adafruit_midi's own buffer holds bytes.
            if self.port.any() or self.midi._in_buf:
                msg = self.midi.receive()
                if msg is not None:
                    if getattr(msg, "_STATUS", None) is None and not hasattr(msg, "data"):
                        raise ValueError("adafruit_midi read {} {!r}".format(
                            type(msg).__name__, getattr(msg, "status", getattr(msg, "data", None))))
                    return msg.__bytes__()  # MicroPython's bytes() never calls __bytes__
            if timeout_ms is not None and waited >= timeout_ms:
                raise bledev.BLETimeoutError("no message in {} ms".format(timeout_ms))
            await bledev.sleep_ms(1)
            waited += 1
