"""Freeze the PyDevices library into a firmware image.

This is an opt-in *freeze* manifest, for an app that wants a standalone build:
one ``micropython.exe``, or one board image, that runs with nothing installed.
Include it from the app's own freeze manifest::

    include("path/to/pydevices/manifest-core.py")

It freezes everything in ``lib/`` at top level, so ``appdev``, ``audiodev``,
``displaydev``, ``multimer``, ``boarddev``, ``events``, ``keys`` and ``wifi``
import under their own names, exactly as they do after a ``mip`` install. The
list is read from ``lib/`` itself, with the same filter the publisher uses, so
a new module there is frozen without anyone editing this file. ``utils/`` is
not frozen: its ``mip.py`` must never sit in front of the firmware's own
``mip``.

For a desktop interpreter, include ``manifest-desktop.py`` instead; it adds
the desktop board config and the pure-Python SDL2 and Win32 bindings.

This is not ``manifest.py``. That one packages the source tree for
installation, and it is the only manifest the publisher reads.

**What freezing costs you.** Frozen modules come before ``lib`` on
``sys.path`` (``.frozen`` is searched first), so a frozen PyDevices shadows any
copy installed with ``mip``. Updating it means rebuilding the firmware. That is
why the org's own interpreters don't freeze it and keep installing with
``mip``; use this manifest only when a single self-contained binary is the
point.
"""

import os

if 0:

    def package(*args, **kwargs):
        pass

    def module(*args, **kwargs):
        pass


# The manifest tools run this file with its own directory as the working
# directory, so "lib" is this checkout's lib/ wherever the build runs from.
for _name in sorted(os.listdir("lib")):
    if _name.startswith(".") or _name in ("__pycache__", "build", "dist"):
        continue
    if os.path.isdir(os.path.join("lib", _name)):
        package(_name, base_path="lib", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
    elif _name.endswith(".py"):
        module(_name, base_path="lib", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
