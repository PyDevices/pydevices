# hmilink

Any screen as a device's front panel. A device holds the true state of
something (a synth rack, a song) as one JSON document. Any number of front
panels show and change it: the device's own screen, a phone's browser, a
control app. They all speak one small contract, so no two screens disagree
with the sound, and a new panel never means touching the device's code.

On the device, give it a model and a transport, and poll it between audio
blocks, so every edit lands on a block boundary:

```python
import hmilink
from hmilink import tcp

device = hmilink.Device(model)                 # a model: describe, apply, telemetry, command
device.add(tcp.serve(9000, page="index.html")) # a phone opens http://<ip>:9000/
while True:
    rack.step()
    pcm.write(block)
    device.poll()
```

On a panel, connect and draw from the document; send ops as the user moves
things:

```python
panel = hmilink.Panel(tcp.connect("192.168.1.42", 9000))
panel.on_op = redraw_one
panel.on_tele = light_leds
while True:
    panel.poll()
    ...
    panel.set("/modules/vco1/params/range", 0.5)
```

The contract is in [`hmilink/__init__.py`](hmilink/__init__.py)'s docstring: a document changed by
JSON Patch ops with JSON Pointer paths, numbered and echoed to every panel;
lossy telemetry; commands and events; and a self-description that says
what the document holds, never how to lay it out.

Transports are swappable and neither side knows which carries it:

| Transport | Device | Panel |
|---|---|---|
| Wi-Fi, TCP (one frame per line) | `tcp.serve(9000)` | `tcp.connect(host, 9000)` |
| Wi-Fi, a browser (same port: HTTP page, WebSocket at `/ws`) | `tcp.serve(9000, page=...)` | the page |
| In-process (the device's own screen; tests) | `local.serve()` | `local.connect(listener)` |
| A UART or USB CDC | `stream.link(uart)` | `stream.link(uart)` |

Runs on MicroPython, CircuitPython and CPython, with no threads and no
asyncio. [`hmilink/tests/run.py`](tests/run.py) runs on all three (CircuitPython has no
sockets on the desktop, so the TCP checks are skipped there).

This is a preview: it isn't released yet, and the names may still change.
