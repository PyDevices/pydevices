# Freezing hmilink into a firmware. Every module is pure Python and runs on
# MicroPython, CircuitPython and CPython; a board carries them all (tcp
# needs sockets, local needs nothing, stream needs a UART or CDC object,
# osc needs sockets).
metadata(
    description="Any screen as a device's front panel: one document, ops, telemetry and events over any transport.",
    version="0.0.1",
    license="MIT",
)

package("hmilink", files=("__init__.py", "tcp.py", "local.py", "stream.py", "osc.py"))
