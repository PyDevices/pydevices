# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Lazy end-device binding for board_peripherals -> board_config.

``board_peripherals.load_peripherals(globals())`` typically calls
``bind_lazy(ns, this_module)``. Apps never import ``boarddev`` directly;
they use ``board_config.PERIPHERALS`` and attribute access.
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
