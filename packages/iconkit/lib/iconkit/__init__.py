# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Material Design icons as 8-bit alpha masks that stay in flash.

``mask("home")`` gives the antialiased shape of an icon as a slice of one big
constant in a frozen module, so an icon costs no RAM. Draw the mask with
`iconkit.lvicons` in LVGL or `iconkit.gfx` in pygraphics. This module imports
neither.

Two sets ship: 128 icons at 24 px and 32 app-tile icons at 48 px. An app with
icons of its own builds a module with ``tools/make_icons.py`` and registers it
with `add`.

Example::

    import iconkit
    view, w, h = iconkit.mask("wifi")   # w * h alpha bytes, row by row
"""

# Sizes that have a module of their own, ``iconkit._a8_<size>``.
_BUILTIN = (24, 48)

# size -> [module, ...]; the shipped module comes first.
_mods = {}


def _modules(size):
    mods = _mods.get(size)
    if mods is None:
        if size not in _BUILTIN:
            raise ValueError(
                "iconkit has no icons at %r px: the shipped sizes are %s. Build a module of your own "
                "with tools/make_icons.py and register it with iconkit.add()." % (size, _BUILTIN)
            )
        mods = _mods[size] = [__import__("iconkit._a8_%d" % size, None, None, ("DATA",))]
    return mods


def mask(name, size=24):
    """The alpha mask of icon *name*.

    Args:
        name (str): A Material icon name such as ``"home"``.
        size (int): 24 or 48, or the size of a module added with `add`.

    Returns:
        ``(data, w, h)``: a memoryview of ``w * h`` alpha bytes, row by row, and the size.

    Raises:
        ValueError: *name* isn't in any module of that size, or no module has that size.
    """
    for m in _modules(size):
        ns = m.NAMES
        if name in ns:
            n = size * size
            i = ns.index(name) * n
            return m.DATA[i : i + n], size, size
    raise ValueError(
        "no icon named %r at %d px; iconkit.names(%d) lists the %d there. Build it into a module "
        "with tools/make_icons.py and register it with iconkit.add()." % (name, size, size, len(_all(size)))
    )


def _all(size):
    out = ()
    for m in _modules(size):
        out += tuple(m.NAMES)
    return out


def names(size=24):
    """Every icon name at *size*, in the order of its module(s).

    Raises:
        ValueError: no module has that size.
    """
    return _all(size)


def add(module):
    """Register an icon module built by ``tools/make_icons.py`` for *module*'s size.

    Args:
        module: A module with ``SIZE``, ``NAMES`` and ``DATA``.

    Raises:
        ValueError: A name is already taken at that size, or ``DATA`` isn't
            ``len(NAMES) * SIZE * SIZE`` bytes.
    """
    size = module.SIZE
    if len(module.DATA) != len(module.NAMES) * size * size:
        raise ValueError(
            "icon module has %d bytes of DATA for %d names at %d px; it should have %d. "
            "Rebuild it with tools/make_icons.py." % (len(module.DATA), len(module.NAMES), size, len(module.NAMES) * size * size)
        )
    if size in _BUILTIN:
        mods = _modules(size)
    else:
        mods = _mods.setdefault(size, [])
    if module in mods:
        raise ValueError("icon module %r is already added" % (module,))
    taken = set()
    for m in mods:
        taken.update(m.NAMES)
    clash = [n for n in module.NAMES if n in taken]
    if clash:
        raise ValueError(
            "icon names already taken at %d px: %s. Rename them in your module's list and rebuild it."
            % (size, ", ".join(clash))
        )
    mods.append(module)
