# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run the portable audio path under MicroPython or CircuitPython.

``test_portability.py`` runs this under every non-CPython interpreter it can
find. It is also useful by hand::

    cd pydevices
    micropython tests/portability_probe.py
    micropython.exe tests/portability_probe.py
    circuitpython tests/portability_probe.py

It exercises the things that have actually broken -- selecting a backend, the
environment helpers that replaced ``os.environ``, and writing PCM (which
consumes bytearray buffers). None of them fail at import, only on first use, so
importing the modules is not enough to prove anything.

This file must itself stay inside the API subset MicroPython and CircuitPython
share: no ``os.path``, no ``pathlib``, no ``unittest``, no ``os.environ``.
Prints ``PORTABILITY OK`` on success; raises (exit 1) on the first failure.
"""

import os
import sys

_SLASH = __file__.replace("\\", "/")
ROOT = _SLASH.rsplit("/", 1)[0] + "/.." if "/" in _SLASH else ".."

for _rel in ("drivers", "lib", "board_configs/desktop"):
    sys.path.insert(0, ROOT + "/" + _rel)

# Headless, and set before SDL initializes either subsystem. Done here rather
# than by the caller because WSL does not forward its environment into
# micropython.exe.
os.putenv("SDL_VIDEODRIVER", "dummy")

_checks = 0


def check(label, ok):
    global _checks
    if not ok:
        raise AssertionError(label)
    _checks += 1
    print("  ok:", label)


def probe_backend_selection():
    """``_select_backend()`` used to reach ``os.environ`` and die on win32."""
    preset = os.getenv("SDL_AUDIODRIVER")

    import board_peripherals

    backend = board_peripherals._select_backend()
    check(
        "selected a backend ({})".format(backend),
        backend in ("sdl2_audio", "pygame_audio", "web_audio", "win_audio"),
    )
    current = os.getenv("SDL_AUDIODRIVER")
    if preset is not None:
        check("an explicit audio driver still wins", current == preset)
    elif sys.platform == "win32" and backend == "pygame_audio":
        check("win32 pygame_audio defaults to directsound", current == "directsound")
    else:
        # Every other combination leaves it to SDL: only pygame's small-chunk
        # playback needs DirectSound, and it costs sdl2_audio latency.
        check("the audio driver is left alone ({})".format(backend), current is None)


def probe_env_helpers():
    """The portable stand-in for ``os.environ``, which only CPython has.

    Checked directly rather than through backend selection: an interpreter
    without pygame never reaches the one place a board config writes an
    environment variable, so that path alone would leave this unguarded.
    """
    try:
        from displaydev import env_get, env_set
    except ImportError:
        print("  skip: displaydev is not installed for this interpreter")
        return

    name = "PYDEVICES_PROBE_VAR"
    check("env_get returns None for an unset name", env_get(name) is None)
    env_set(name, "directsound")
    check("env_set is visible to env_get", env_get(name) == "directsound")
    check("env_set is visible to os.getenv", os.getenv(name) == "directsound")


def probe_buffer_consumption():
    """Writing PCM used to raise ``TypeError`` on bytearray item deletion."""
    # Never open the real sink from a test: a second stream on the host sink
    # fights whatever else is playing, and this way no audio hardware is needed.
    os.putenv("SDL_AUDIODRIVER", "dummy")

    from audiodev import AudioFormat, sdl2_audio

    fmt = AudioFormat(24000, 1, 16)
    device = sdl2_audio.pcm_out(fmt)
    device.open()

    # Small enough that the first queued piece overflows it, so the trim branch
    # runs without writing megabytes.
    device._shadow_limit = 1024

    # A recognizable ramp, so the checks below can tell the tail of the buffer
    # from the head -- a slice that trimmed the wrong end would still have the
    # right length.
    pattern = bytearray()
    for value in range(256):
        pattern.append(value)

    piece = device._coalesce_bytes
    written = bytearray()
    while len(written) < piece + piece // 2:
        written.extend(pattern)

    device.write(written)
    device.service()

    check("queued PCM to SDL ({} bytes)".format(device._queued_total), device._queued_total > 0)
    check(
        "consumed from the front of _coalesce ({} left)".format(len(device._coalesce)),
        len(device._coalesce) == len(written) - device._queued_total,
    )
    check(
        "trimmed _shadow to its limit ({} bytes)".format(len(device._shadow)),
        len(device._shadow) <= device._shadow_limit,
    )
    check(
        "_shadow kept the tail, not the head",
        bytes(device._shadow)
        == bytes(written[: device._queued_total])[-device._shadow_limit :],
    )

    device.clear()
    check(
        "clear() empties both buffers",
        len(device._coalesce) == 0 and len(device._shadow) == 0,
    )
    device.close()


def probe_latency_profile():
    """``latency="low"`` must build and play on every interpreter, not just CPython."""
    os.putenv("SDL_AUDIODRIVER", "dummy")

    from audiodev import AudioFormat, sdl2_audio

    fmt = AudioFormat(24000, 1, 16)
    device = sdl2_audio.pcm_out(fmt, latency="low")
    device.open()
    check(
        "low profile shortened the coalesce window ({} bytes)".format(device._coalesce_bytes),
        device._coalesce_bytes < 24000 * 2 * 100 // 1000,
    )
    device.write(bytes(device._coalesce_bytes * 2))
    device.service()
    check("low profile queued PCM ({} bytes)".format(device._queued_total), device._queued_total > 0)
    device.close()

    failed = False
    try:
        sdl2_audio.pcm_out(fmt, latency="nope")
    except ValueError:
        failed = True
    check("an unknown profile raises instead of falling back", failed)


def probe_board_config():
    """``board_config`` is what apps import; it must load headless."""
    try:
        import displaydev  # noqa: F401
    except ImportError:
        print("  skip: displaydev is not installed for this interpreter")
        return

    import board_config

    check("board_config built a display", hasattr(board_config, "display_drv"))
    check("board_config leaves app creation to the application", not hasattr(board_config, "app"))
    check("board_config bound the audio roles", "audio_out" in board_config.PERIPHERALS)


def main():
    probe_backend_selection()
    probe_env_helpers()
    probe_buffer_consumption()
    probe_latency_profile()
    probe_board_config()
    print(
        "PORTABILITY OK ({} checks, {} {})".format(
            _checks, sys.implementation.name, sys.platform
        )
    )


try:
    main()
except Exception as exc:
    # Re-raised so the interpreter prints a traceback and exits non-zero.
    print("FAIL:", exc)
    raise
