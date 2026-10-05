"""Freeze the universal desktop board config into a desktop or browser build.

One config serves every non-MCU host: ``AutoDisplay`` picks SDL, Windows GDI,
the browser canvas and so on when it is imported, and the panel's size and
scale come from ``PYDEVICES_WIDTH``, ``PYDEVICES_HEIGHT`` and friends. So a
unix, windows or webassembly build carries this one, and a ``board_config.py``
beside your script still wins (the script's directory comes before
``.frozen`` on ``sys.path``). Microcontroller images never freeze a board
config: each board installs its own.

It freezes ``board_config``, ``board_peripherals``, and the desktop-only
helpers from ``utils/``: the pure-Python SDL2 and Win32 bindings the desktop
display, audio and timer backends open a window and a sound device through
(a native ``usdl2`` built in still wins), and ``frame_recorder``. It does not
bring pydevices itself.

micropython-pydevices' desktop and browser variants (``--variant pydevices`` on
unix, windows and webassembly) include this file, so a build never names it.
"""

if 0:

    def module(*args, **kwargs):
        pass


for _name in ("board_config.py", "board_peripherals.py"):
    module(_name, opt=3)  # type: ignore[name-defined]  # noqa: PGH003

for _name in ("usdl2.py", "uwin32.py", "frame_recorder.py"):
    module(_name, base_path="../../utils", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
