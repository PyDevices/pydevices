"""Portable USB host and device contracts for MicroPython and CPython.

Backends subclass :class:`Host` and :class:`Device`. Optional host selection
lives in :mod:`usbif.auto` and is never imported from here, matching
``audiodev`` and ``displaydev``.

Two rules shape everything in this package.

**Python configures and observes; C moves isochronous bytes.** A caller sets a
stream up and watches it run. It never pumps audio or video frames through the
interpreter, because isochronous endpoints must be serviced every USB frame and
the VM cannot promise that (see the transport note below).

**Capabilities are discovered, never assumed.** The same import succeeds on a
board with a full host stack, on a desktop where the OS owns the bus, and on a
port with no USB at all. What differs is what :meth:`Host.capabilities` and
:meth:`Device.capabilities` return, so application code branches on a
frozenset rather than on ``ImportError`` or a chip name.

Transport, and why events arrive by draining rather than by callback: on ESP32
a C-side callback reaches Python through ``mp_sched_schedule``, which is
excellent while the VM runs bytecode and catastrophic inside a long C call.
Measured on an ESP32-S3 at a 1 kHz event rate, a ``sha256`` pass over 120 KB
lost 76% of events and flash writes lost 99% with a single 1537 ms stall.
Backends therefore capture events into a buffer the moment they occur -- in
interrupt context on an MCU, from the OS on a desktop -- and Python collects
them with :meth:`Host.poll`. Delivery latency then equals how often the
application polls, which it controls, instead of what the VM happened to be
doing when the event arrived. Buffer overflow is reported (see
:attr:`Host.overflowed`), never silent, because the mechanism this replaces
failed silently.
"""

try:
    from collections import namedtuple
except ImportError:  # pragma: no cover - ucollections on older firmware
    from ucollections import namedtuple

import events

# --- Event types -----------------------------------------------------------
#
# Registered here rather than in a backend so that ``events.USBATTACH`` exists
# as soon as the contract is imported, whether or not a backend is available.
# Registration is idempotent: ``events.register_event`` raises on a duplicate,
# and this module may legitimately be imported twice under different names
# (``usbif`` and ``pydevices.lib.usbif``) in the same process.
for _name in ("USBATTACH", "USBDETACH"):
    if not hasattr(events, _name):
        events.register_event(_name, fields="type device")
del _name

# --- Device classes --------------------------------------------------------
#
# Spelled as strings so a capability set is printable and comparable without
# importing this module -- a board can report what it supports over a REPL or
# a log line. The values are the USB class names a user would recognise, not
# the numeric bInterfaceClass codes, which stay inside the backends.
HID = "hid"
MSC = "msc"
CDC = "cdc"
MIDI = "midi"
UAC = "uac"
UVC = "uvc"

CLASSES = (HID, MSC, CDC, MIDI, UAC, UVC)

# Speeds, as reported by DeviceInfo.speed. ``None`` means the backend cannot
# tell -- an honest answer the OS sometimes gives on a desktop.
LOW, FULL, HIGH = "low", "full", "high"


def check_class(name):
    """Validate a USB class name, returning it unchanged.

    Raises rather than ignoring an unknown name, so a typo surfaces as an
    error instead of a capability that is silently never satisfied.
    """
    if name not in CLASSES:
        raise ValueError("unknown USB class {!r}; expected one of {}".format(name, CLASSES))
    return name


# --- Device description ----------------------------------------------------
#
# A namedtuple rather than an object with properties: it is cheap to allocate
# on an MCU, it compares by value (which the parity harness relies on to assert
# that both backends describe the same device identically), and it is
# immutable, so a stale copy held by an application cannot misreport a device
# that has since detached.
#
# ``id`` is backend-assigned and opaque: a bus path on Linux, an instance path
# on Windows, an enumeration handle on an MCU. It is the handle every per-class
# call takes. It is stable while the device stays attached and is never reused
# for a different device within a session.
# Field names are spelled out as a constant as well as passed to namedtuple:
# MicroPython's namedtuple has no ``_fields``, so a portable test (or any
# caller wanting to check the shape) has nothing to read otherwise. This is
# the canonical description of the record either way.
DEVICE_FIELDS = ("id", "vid", "pid", "product", "serial", "classes", "speed")

DeviceInfo = namedtuple("DeviceInfo", " ".join(DEVICE_FIELDS))  # noqa: PYI024

# Same reasoning for the event payloads, which carry the event type and the
# device it concerns.
EVENT_FIELDS = ("type", "device")


def describe(info):
    """One-line human description of a device, for logs and REPL use."""
    name = info.product or "USB device"
    ident = "%04x:%04x" % (info.vid or 0, info.pid or 0)
    kinds = ",".join(sorted(info.classes)) if info.classes else "?"
    return "{} [{}] ({})".format(name, ident, kinds)


class _Role:
    """Shared capability, lifecycle, and event-buffer housekeeping."""

    role = None

    def __init__(self):
        self.is_open = False
        self._overflowed = False

    def capabilities(self):
        """USB classes this backend can actually work with, as a frozenset.

        An empty set is a valid and common answer: a desktop has no host role
        to offer beyond what the OS already owns, and a port without USB
        offers nothing at all. Callers branch on membership.
        """
        return frozenset()

    def supports(self, name):
        """True if ``name`` (a class constant) is in :meth:`capabilities`."""
        return check_class(name) in self.capabilities()

    @property
    def overflowed(self):
        """True if events were lost since the last :meth:`poll`.

        The buffer is sized for the worst observed VM stall, but a caller that
        stops polling entirely can still outrun it. This flag is how that gets
        said out loud; the transport it replaces dropped events in silence.
        """
        return self._overflowed

    def _start(self):
        pass

    def _stop(self):
        pass

    def start(self):
        if self.is_open:
            return self
        self._start()
        self.is_open = True
        return self

    def stop(self):
        if not self.is_open:
            return
        try:
            self._stop()
        finally:
            self.is_open = False

    deinit = stop

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.stop()


class Host(_Role):
    """The board (or desktop process) drives attached USB peripherals.

    Subclasses implement :meth:`_devices` and :meth:`_drain`, and set
    :meth:`capabilities`.
    """

    role = "host"

    def _devices(self):
        raise NotImplementedError("Host subclasses must implement _devices")

    def devices(self):
        """Currently attached devices, as a tuple of :class:`DeviceInfo`."""
        self.start()
        return tuple(self._devices())

    def find(self, cls):
        """Attached devices offering a given class, e.g. ``usbif.HID``."""
        check_class(cls)
        return tuple(d for d in self.devices() if cls in d.classes)

    def _drain(self):
        """Return newly buffered events as a list. Subclasses implement."""
        raise NotImplementedError("Host subclasses must implement _drain")

    def poll(self):
        """Collect buffered events and return them, newest last.

        Call this from the application's normal service loop. Events are
        already captured by the time it runs, so a late poll costs latency,
        never data, until the buffer is full.
        """
        self.start()
        self._overflowed = False
        return tuple(self._drain())


class Device(_Role):
    """The board presents itself to a computer as a USB peripheral.

    Configuration only: the classes that move isochronous bytes (UAC, UVC) run
    entirely in C and are observed from Python, never fed by it.
    """

    role = "device"

    def _drain(self):
        return ()

    def poll(self):
        self.start()
        self._overflowed = False
        return tuple(self._drain())


class NullHost(Host):
    """A host that offers nothing, for ports without USB host support.

    Exists so that ``usbif.auto`` can always return an object: application
    code checks ``capabilities()`` once instead of guarding every import.
    """

    def capabilities(self):
        return frozenset()

    def _devices(self):
        return ()

    def _drain(self):
        return ()


__all__ = (
    "CDC",
    "CLASSES",
    "DEVICE_FIELDS",
    "EVENT_FIELDS",
    "FULL",
    "HID",
    "HIGH",
    "LOW",
    "MIDI",
    "MSC",
    "UAC",
    "UVC",
    "Device",
    "DeviceInfo",
    "Host",
    "NullHost",
    "check_class",
    "describe",
)
