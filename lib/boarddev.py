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
