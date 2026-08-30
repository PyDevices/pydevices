"""USB host backend over the ``usbif`` native C module.

This is the Python half of the MCU backend: it configures, observes, and
drains, while the C module owns enumeration, the class drivers, and -- for
UAC and UVC -- the isochronous byte movement Python must never be asked to do.

The division is deliberate and measured. See the transport note in
``usbif/__init__.py``: on ESP32 a scheduler-delivered callback loses most of a
1 kHz event stream during a blocking C call, so ``_usbif`` captures events into
a lock-free ring buffer in interrupt context and this module drains it. The
buffer is sized for the worst observed VM stall rather than a round number, and
reports overflow instead of dropping in silence.

The C module surface this expects, which is the contract the native side must
satisfy:

``_usbif.host_start(classes)``  start the daemon and the class drivers for the
                               requested class names; returns the set actually
                               started.
``_usbif.host_stop()``          stop them and release the controller.
``_usbif.host_devices()``       tuple of ``(id, vid, pid, product, serial,
                                classes, speed)`` tuples for attached devices.
``_usbif.host_drain(limit)``    pop up to ``limit`` buffered events, each
                                ``(kind, device_tuple)``; returns
                                ``(events, overflowed)``.
``_usbif.capabilities()``       class names this firmware was built with.
"""

import events

from . import DeviceInfo, Host

try:
    import _usbif
except ImportError:  # pragma: no cover - exercised only off-target
    _usbif = None

# Event kinds as the C side numbers them. Kept small and integral so the ring
# buffer entry stays a fixed-size record that can be written from an ISR.
_ATTACH = 0
_DETACH = 1

# Events drained per poll. Bounded so a burst cannot turn one poll into an
# unbounded allocation storm on a device with 8 KB of free heap; whatever is
# left stays buffered for the next call.
DRAIN_LIMIT = 64


def _require():
    if _usbif is None:
        raise ImportError(
            "the usbif native module is not present in this firmware; "
            "build it as a user C module (see the usbif repository) or use "
            "usbif.auto.host() to get a backend appropriate to this port"
        )
    return _usbif


class NativeHost(Host):
    """USB host on hardware, backed by the native module."""

    def __init__(self, classes=None, drain_limit=DRAIN_LIMIT):
        super().__init__()
        self.classes = tuple(classes) if classes else None
        self.drain_limit = int(drain_limit)
        self._started = frozenset()

    def capabilities(self):
        if _usbif is None:
            return frozenset()
        return frozenset(_usbif.capabilities())

    def _start(self):
        wanted = self.classes if self.classes is not None else tuple(self.capabilities())
        self._started = frozenset(_require().host_start(wanted))

    def _stop(self):
        _require().host_stop()
        self._started = frozenset()

    def _devices(self):
        return tuple(DeviceInfo(*row) for row in _require().host_devices())

    def _drain(self):
        raw, overflowed = _require().host_drain(self.drain_limit)
        self._overflowed = bool(overflowed)
        out = []
        for kind, row in raw:
            info = DeviceInfo(*row)
            if kind == _ATTACH:
                out.append(events.Usbattach(events.USBATTACH, info))
            elif kind == _DETACH:
                out.append(events.Usbdetach(events.USBDETACH, info))
        return out


__all__ = ("NativeHost",)
