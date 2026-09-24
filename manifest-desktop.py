"""Freeze PyDevices and its desktop board config into a desktop interpreter.

This is an opt-in *freeze* manifest, for an app that wants one
``micropython.exe`` (or unix ``micropython``) that runs with nothing
installed. Include it from the app's own freeze manifest, next to the port's
standard content and the app itself::

    include("$(PORT_DIR)/variants/standard/manifest.py")
    include("$(MPY_DIR)/../pydevices/manifest-desktop.py")
    include("../manifest.py")  # the app

It freezes, all at top level:

- everything ``manifest-core.py`` freezes (the whole of ``lib/``);
- the desktop board config, ``board_config.py`` and ``board_peripherals.py``
  from ``board_configs/desktop``;
- ``usdl2.py`` and ``uwin32.py`` from ``utils/``, the pure-Python SDL2 and
  Win32 bindings that the desktop display, audio and timer backends open a
  window and a sound device through. A native ``usdl2`` compiled into the
  firmware still wins: built-in modules are found before frozen ones.
  ``frame_recorder.py`` comes too, for display recording.

It does not freeze ``utils/mip.py`` (it must never sit in front of the
firmware's own ``mip``) or ``utils/micropython.py`` (a CPython shim).

The binary still needs the SDL2 shared library on the machine when a display
opens through SDL (unix, and Windows' fallback path); Windows' own path uses
only system DLLs.

This is not ``manifest.py``. That one packages the source tree for
installation, and it is the only manifest the publisher reads.

**What freezing costs you.** Frozen modules come before ``lib`` on
``sys.path`` (``.frozen`` is searched first), so a frozen PyDevices shadows any
copy installed with ``mip``, including ``~/.micropython/lib``. Updating it
means rebuilding the binary. That is why the org's own interpreters don't
freeze it and keep installing with ``mip``; use this manifest only when a
single self-contained binary is the point.
"""

if 0:

    def include(*args, **kwargs):
        pass

    def module(*args, **kwargs):
        pass


include("manifest-core.py")  # type: ignore[name-defined]  # noqa: PGH003

for _name in ("board_config.py", "board_peripherals.py"):
    module(_name, base_path="board_configs/desktop", opt=3)  # type: ignore[name-defined]  # noqa: PGH003

for _name in ("usdl2.py", "uwin32.py", "frame_recorder.py"):
    module(_name, base_path="utils", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
