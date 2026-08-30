"""Optional host backend selection. Backends never import this module."""

import sys


def _is_micropython():
    return getattr(getattr(sys, "implementation", None), "name", "") == "micropython"


def _module_available(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def select_backend():
    """Return the module name of the first usable host backend.

    Unlike ``audiodev.auto``, this never raises: a port with no USB support is
    an ordinary outcome, not a configuration error, and the caller is expected
    to branch on ``capabilities()`` anyway. The fallback backend enumerates
    nothing and reports an empty capability set.
    """
    if _module_available("_usbif"):
        return "native_usb"
    if sys.platform in ("linux", "linux2") or (
        _is_micropython() and sys.platform == "linux"
    ):
        return "linux_usb"
    return None


def host(**kwargs):
    """Construct the host for this platform, or a :class:`usbif.NullHost`."""
    name = select_backend()
    if name == "native_usb":
        from .native_usb import NativeHost

        return NativeHost(**kwargs)
    if name == "linux_usb":
        from .linux_usb import LinuxHost

        return LinuxHost(**kwargs)
    from . import NullHost

    return NullHost()


__all__ = ("host", "select_backend")
