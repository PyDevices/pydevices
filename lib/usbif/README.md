# usbif

Portable USB host and device contracts, with one backend per platform — the
same surface on a board and on a workstation, so an application written for
one runs on the other.

```python
from usbif import auto
import usbif, events

host = auto.host().start()
for info in host.devices():
    print(usbif.describe(info))

while True:
    for event in host.poll():
        if event.type == events.USBATTACH:
            print("plugged in:", usbif.describe(event.device))
    ...
```

## What the pieces are

| Module | Role |
|---|---|
| `usbif` | The contracts: `Host`, `Device`, `DeviceInfo`, the class names, and the `USBATTACH`/`USBDETACH` event types |
| `usbif.auto` | Picks a backend. Never imported by a backend, and never raises — a port with no USB returns a `NullHost` |
| `usbif.linux_usb` | Linux, WSL, and containers, reading `/sys/bus/usb/devices` |
| `usbif.native_usb` | Hardware, over the `usbif` native C module |

## Two rules worth knowing before you read the code

**Capabilities are discovered, never assumed.** `host.capabilities()` returns a
frozenset of class names, and it is legitimately empty — on a desktop the OS
owns the bus, and on a port without USB there is nothing to own. Enumeration
and hot-plug always work; the capability set says which classes this backend
can carry *traffic* for. Branch on the set, not on `ImportError`.

**Events are drained, not delivered.** `host.poll()` returns what has been
buffered since the last call. This is not a stylistic choice: on ESP32 a
C-side callback reaches Python through `mp_sched_schedule`, which is excellent
while the VM runs bytecode and collapses inside a long C call. Measured on an
ESP32-S3 at 1 kHz, a `sha256` pass over 120 KB lost 76% of events, and flash
writes lost 99% with a single 1537 ms stall. Backends therefore capture events
the moment they happen and hand them over when asked, so a late poll costs
latency — which the application controls — rather than data. Overflow is
reported through `host.overflowed` rather than passing in silence.

## Tests

`tests/test_usbif.py` in this repository is a conformance suite, not a
Linux test: the same assertions run against every backend, which is what keeps
the two implementations honest about being one API. The Linux backend is
exercised against a synthetic sysfs tree so the suite behaves the same on a
laptop with devices attached, in CI with none, and on a board.

```bash
python -m unittest discover -s tests -p "test_usbif.py"
```
