# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""What the SIG fitness and sensor services share: sensor locations and the
control point that answers with an indication."""

from . import BLEError

#: Sensor Location (0x2A5D) values, by number. Cycling and running services
#: share this list.
LOCATIONS = (
    "other",
    "top of shoe",
    "in shoe",
    "hip",
    "front wheel",
    "left crank",
    "right crank",
    "left pedal",
    "right pedal",
    "front hub",
    "rear dropout",
    "chainstay",
    "rear wheel",
    "rear hub",
    "chest",
    "spider",
    "chain ring",
)

# Control point result codes, the same in all three services.
SUCCESS = 1
OP_CODE_NOT_SUPPORTED = 2
INVALID_PARAMETER = 3
OPERATION_FAILED = 4

# Control point opcodes the cycling speed, running speed and cycling power
# services share by number.
SET_CUMULATIVE_VALUE = 0x01


def check_location(location):
    """``location`` as a Sensor Location number (0 to 16), or raise `ValueError`."""
    location = int(location)
    if not 0 <= location < len(LOCATIONS):
        raise ValueError("a sensor location is 0 to %d" % (len(LOCATIONS) - 1))
    return location


def event_time(seconds, units_per_second):
    """A sensor event time in seconds as the 16-bit counter the services send."""
    return int(seconds * units_per_second) & 0xFFFF


async def serve_control_point(characteristic, handle, response_opcode):
    """Answer every write to a control point, forever.

    ``handle(opcode, parameter)`` returns ``(result, extra)``: a result code
    and the bytes that follow it in the response. The response goes back to
    the writer as an indication: ``[response_opcode, opcode, result] + extra``.

    On MicroPython the indication waits for the central's acknowledgement. On
    CircuitPython `_bleio` can't report one, so it returns once the
    indication is queued. A central that hasn't subscribed to the control
    point's indications gets no response.
    """
    while True:
        connection, data = await characteristic.written()
        data = bytes(data)
        if not data:
            continue
        result, extra = handle(data[0], data[1:])
        try:
            await characteristic.indicate(connection, bytes((response_opcode, data[0], result)) + extra)
        except BLEError:
            pass  # the central went away or never subscribed
