"""Optional backend selection. Nothing in bledev imports this module.

    import bledev.auto
    ble = bledev.auto.adapter()

picks, in order: ``mpble`` where MicroPython's ``bluetooth`` module exists,
``webble`` in a browser (PyScript, Pyodide, the Workbench simulator), and
``bleak`` on CPython when bleak is installed (``pip install pydevices[ble]``).
Pass ``backend="fake"`` (or set ``BLEDEV_BACKEND``) to force one; extra
keyword arguments go to the backend's constructor.

A host with none raises :class:`bledev.UnsupportedError` saying what to install.
"""

import sys

from . import UnsupportedError

#: backend name -> (module, class). Each module stands alone and never imports this one.
BACKENDS = {
    "mpble": ("bledev.mpble", "MPBLE"),
    "bleak": ("bledev.bleak", "BleakBLE"),
    "webble": ("bledev.webble", "WebBLE"),
    "fake": ("bledev.fake", "FakeBLE"),
}


def _importable(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _in_browser():
    if sys.platform in ("emscripten", "webassembly"):
        return True
    return _importable("_wasm_bridge") or _importable("pyodide")


def backend_name():
    """The backend this host would get, or ``None`` if it has no BLE."""
    impl = getattr(sys, "implementation", None)
    impl = getattr(impl, "name", "")
    if impl in ("micropython", "circuitpython"):
        if _in_browser():
            return "webble"
        if _importable("bluetooth"):
            return "mpble"
        return None  # CircuitPython's _bleio waits for bledev.cpble
    if _in_browser():
        return "webble"
    if _importable("bleak"):
        return "bleak"
    return None


def _env_backend():
    try:
        import os

        return os.getenv("BLEDEV_BACKEND")
    except Exception:
        return None


def adapter(backend=None, **kwargs):
    """Construct the adapter for this host (or for ``backend``)."""
    name = backend or _env_backend() or backend_name()
    if name is None:
        raise UnsupportedError(
            "no BLE backend on this host: on CPython, pip install 'pydevices[ble]' "
            "for bleak; on MicroPython, use firmware built with bluetooth"
        )
    if name not in BACKENDS:
        raise UnsupportedError("unknown bledev backend {!r}; one of {}".format(name, sorted(BACKENDS)))
    module_name, class_name = BACKENDS[name]
    module = __import__(module_name, None, None, [class_name])
    return getattr(module, class_name)(**kwargs)
