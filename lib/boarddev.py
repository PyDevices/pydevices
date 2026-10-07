# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Lazy end-device binding for board_peripherals -> board_config.

``board_peripherals.load_peripherals(globals())`` typically calls
``bind_lazy(ns, this_module)``. Apps normally use ``board_config.PERIPHERALS``
and attribute access instead of importing this module.

It also carries the one thing neither ``audiodev`` nor a board can answer on
its own: whether this machine's audio comes from a board or from a host
backend. See :func:`pcm_out`.

And it is where the portable environment helpers live -- :func:`env_get`,
:func:`env_int`, :func:`env_float`, :func:`env_bool` and :func:`env_set` --
because a board config, an app and every PyDevices package read their
``PYDEVICES_*`` settings through them, on interpreters where ``os.environ``
may not exist::

    from boarddev import env_int, env_set

    env_set("PYDEVICES_WIDTH", 800)   # before board_config is imported
    period = env_int("PYDEVICES_REFRESH_MS", 0)

This module imports nothing at module scope, so any package -- ``displaydev``
included -- can import from it without a cycle. Keep it that way.
"""


def bind_lazy(ns, peripherals_mod):
    """Install module ``__getattr__`` / ``__dir__`` on *ns* for lazy roles.

    Each name in ``peripherals_mod.PERIPHERALS`` maps to
    ``peripherals_mod.<name>``. Names in optional
    ``peripherals_mod.FACTORY_ROLES`` (a subset of ``PERIPHERALS``) are
    bound as the factory callable itself — first access does not invoke it.
    That is the audio pattern: ``board_config.audio_out(format=...)`` matches
    ``audiodev.auto.audio_out``. Every other role stays construct-on-getattr:
    first access calls the zero-arg factory, caches the object into
    ``ns[name]``, and further access hits the module dict (no ``__getattr__``).
    """
    roles = peripherals_mod.PERIPHERALS
    factory_roles = frozenset(getattr(peripherals_mod, "FACTORY_ROLES", ()))

    def __getattr__(name):
        if name not in roles:
            raise AttributeError("module has no attribute {!r}".format(name))
        factory = getattr(peripherals_mod, name)
        if name in factory_roles:
            ns[name] = factory
            return factory
        obj = factory()
        ns[name] = obj
        return obj

    def __dir__():
        names = list(ns.keys())
        for role in roles:
            if role not in ns:
                names.append(role)
        return sorted(names)

    ns["__getattr__"] = __getattr__
    ns["__dir__"] = __dir__


# --- host-or-board audio resolution ---------------------------------------
#
# An app that runs on both a board and a desktop used to write this by hand::
#
#     try:
#         from audiodev.auto import audio_out
#         pcm = audio_out(fmt, latency="low")
#         pcm = getattr(pcm, "transport", pcm)     # which type did I get?
#     except (ImportError, OSError):
#         import board_config
#         pcm = board_config.audio_out.transport
#
# Both getattrs there are symptoms. The second is this question -- host or
# board -- and it cannot be answered inside ``audiodev``: importing board
# configs from there would cost audiodev its standalone-ness, and audiodev is
# meant to be usable with no pydevices board tree at all. ``boarddev`` is
# already the seam between the two, so it answers here.
#
# Note it resolves to ``board_peripherals``, never ``board_config``. On some
# boards importing ``board_config`` initialises the display -- on the
# ESP32-P4 that means MIPI DSI, which stalls the VM -- and a headless audio
# app has no use for a display anyway. That is the whole point of the
# non-graphics idiom.


def audio_provider():
    """Return the module supplying this machine's audio factories.

    ``board_peripherals`` when this machine has one, else
    ``audiodev.auto``. A desktop ``board_peripherals`` forwards to
    ``audiodev.auto`` itself, so preferring the board module is right in
    both cases.
    """
    try:
        import board_peripherals

        return board_peripherals
    except ImportError:
        from audiodev import auto

        return auto


def _role(name, format, kwargs):
    provider = audio_provider()
    factory = getattr(provider, name, None)
    if factory is None:
        raise AttributeError(
            "{} provides no {!r} role".format(
                getattr(provider, "__name__", provider), name
            )
        )
    return factory(format, **kwargs)


def pcm_out(format=None, **kwargs):
    """Raw :class:`~audiodev.PCMOutput` from board or host, same call.

    Push bytes at it with ``write()``; no sample graph is pulled, so this
    needs no audiodsp in firmware.
    """
    return _role("pcm_out", format, kwargs)


def pcm_in(format=None, **kwargs):
    """Raw :class:`~audiodev.PCMInput` from board or host, same call."""
    return _role("pcm_in", format, kwargs)


def audio_out(format=None, **kwargs):
    """:class:`~audiodev.sample_out.AudioOut` sample player, board or host."""
    return _role("audio_out", format, kwargs)


# --- portable environment variables ---------------------------------------
#
# CPython has ``os.environ``; MicroPython and CircuitPython have ``getenv``
# and sometimes ``putenv``, and some ports have neither. ``env_set`` records
# every value in a process-local table as well as in whatever the host
# offers, so a value a page or a board config sets is visible to every
# reader in the same process, on every interpreter.

# Process-local overrides for ports without ``os.environ`` / ``os.putenv``.
_overrides = {}


def env_set(name, value):
    """Set an environment variable portably (CPython, MicroPython, CircuitPython).

    Always records a process-local override so ``env_bool`` sees the value even
    when the host ``os`` module has no ``environ``. When available, also updates
    ``os.environ`` or calls ``os.putenv``.
    """
    text = "" if value is None else str(value)
    _overrides[name] = text

    import os

    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            environ[name] = text
            return
        except Exception:
            pass
    putenv = getattr(os, "putenv", None)
    if putenv is not None:
        try:
            putenv(name, text)
        except Exception:
            pass


def env_bool(name, default=False):
    """Read a truthy/falsey environment variable with a portable fallback chain."""
    raw = _env_raw(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return bool(default)


def env_get(name, default=None):
    """Read a string environment variable portably (honors ``env_set`` overrides)."""
    raw = _env_raw(name)
    if raw is None:
        return default
    return raw


def env_int(name, default=0):
    """Read an integer environment variable portably (honors ``env_set`` overrides)."""
    raw = _env_raw(name)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)


def env_float(name, default=0.0):
    """Read a floating-point environment variable portably."""
    raw = _env_raw(name)
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return float(default)


def _env_raw(name):
    if name in _overrides:
        return _overrides[name]

    import os

    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            value = environ.get(name)
        except Exception:
            value = None
        if value is not None:
            return value
    getenv = getattr(os, "getenv", None)
    if getenv is None:
        return None
    try:
        return getenv(name)
    except Exception:
        return None
