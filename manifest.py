"""PyDevices as a micropython-lib package: freeze it into a firmware, or
require() it from another manifest.

It carries everything in ``lib/`` at top level, so ``appdev``, ``audiodev``,
``bledev``, ``displaydev``, ``multimer``, ``boarddev``, ``events``, ``keys``
and ``wifi`` import under their own names, exactly as they do after a ``mip``
install. The list is read from ``lib/`` itself, so a new module there is
included without anyone editing this file. ``utils/`` is not: its ``mip.py``
must never sit in front of the firmware's own ``mip``.

With micropython-pydevices, ``build_mp.py --modules pydevices`` (or ``all``)
freezes it. From your own freeze manifest::

    include("path/to/pydevices")

For a desktop interpreter, include ``manifest-desktop.py`` instead; it adds
the desktop board config and the pure-Python SDL2 and Win32 bindings.

This file is not what ``mip`` installs from. The org's publisher builds the
``pydevices`` and ``pydevices-desktop`` mip packages from ``lib/``, ``utils/``
and ``mip-split.toml`` directly, with manifests of its own.

**What freezing costs you.** Frozen modules come before ``lib`` on
``sys.path`` (``.frozen`` is searched first), so a frozen PyDevices shadows any
copy installed with ``mip``. Updating it means rebuilding the firmware. Freeze
it where one self-contained image is the point, or where a page should load
without fetching it (the webassembly build); elsewhere, install with ``mip``.
"""

import os

if 0:

    def metadata(*args, **kwargs):
        pass

    def package(*args, **kwargs):
        pass

    def module(*args, **kwargs):
        pass


with open("VERSION") as _f:
    _version = _f.read().strip()

metadata(  # type: ignore[name-defined]  # noqa: PGH003
    description="PyDevices: display, audio, input, timing and app support for MicroPython, CircuitPython and CPython",
    version=_version,
    license="MIT",
    author="Brad Barnett",
)

# The manifest tools run this file with its own directory as the working
# directory, so "lib" is this checkout's lib/ wherever the build runs from.
for _name in sorted(os.listdir("lib")):
    if _name.startswith(".") or _name in ("__pycache__", "build", "dist"):
        continue
    if os.path.isdir(os.path.join("lib", _name)):
        package(_name, base_path="lib", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
    elif _name.endswith(".py"):
        module(_name, base_path="lib", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
