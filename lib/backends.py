# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""A registry of backends, so ``AutoDisplay`` and ``audiodev.auto`` can pick one you wrote.

Experimental: the names and the calling convention may still change.

A backend registers a name and a lazy ``"module:Class"`` string, so
registering imports nothing::

    import backends
    backends.register("display", "hls", "hls_display:HlsDisplay", probe=have_ffmpeg)

A board config says which registered backends it wants, in order::

    backends.require("display", "hls", module="hls_display")
    display_drv = AutoDisplay(1280, 720, tv=TV)   # extra keywords go to the winner

``kind`` is ``"display"`` or ``"audio"``. The search order is:

1. the environment variable (``PYDEVICES_DISPLAY`` or ``PYDEVICES_AUDIO``),
   if set. It names one backend and nothing else is tried;
2. the backends a config ``require``d, in order, skipping any whose
   ``probe()`` says no;
3. the backends that ship in the box, in their fixed order, on the host
   that can run them.

A backend registered by someone else is never picked in step 3. Something has
to ``require`` it, or the user has to name it, so a backend that streams to a
TV never chooses itself.

There is no scanning. On MicroPython, ``require`` imports the module by name and
importing registers it; a frozen module imports like any other.
"""

import sys

__all__ = ["Decline", "register", "require", "names", "spec", "env", "candidates", "load"]


class Decline(Exception):
    """Raised by a backend's factory to say "not on this machine"; the next one is tried."""


# kind -> list of [name, spec, probe, builtin]; a list because order matters and
# MicroPython dicts do not promise it
_entries = {}
# kind -> names a config required, in the order it asked
_required = {}


def _find(kind, name):
    for entry in _entries.get(kind, ()):
        if entry[0] == name:
            return entry
    return None


def register(kind, name, spec, probe=None, builtin=False):
    """Make *name* a backend of *kind*; imports nothing.

    *spec* is ``"module:Class"`` (``"module"`` alone for an audio backend, which
    is a module with ``pcm_out`` and ``pcm_in``). *probe*, if given, is called
    with no arguments and returns false when this machine can't run the
    backend. Registering a name again replaces it in place.

    *builtin* is for backends that ship in the box: they are the ones the
    third step of the search order considers, in the order they registered.
    """
    entry = [name, spec, probe, bool(builtin)]
    entries = _entries.setdefault(kind, [])
    for i in range(len(entries)):
        if entries[i][0] == name:
            entries[i] = entry
            return
    entries.append(entry)


def names(kind):
    """The registered backend names of *kind*, in registration order."""
    return [entry[0] for entry in _entries.get(kind, ())]


def spec(kind, name):
    """The spec string *name* was registered with, or ``None``."""
    entry = _find(kind, name)
    return entry[1] if entry else None


def env(name):
    """An environment variable's value or ``None``, through ``boarddev`` when it is there."""
    try:
        from boarddev import env_get
    except ImportError:
        import os

        return os.getenv(name)
    return env_get(name)


def require(kind, name, module=None):
    """Ask for backend *name* to be tried by ``auto``, ahead of the built-in ones.

    If *name* isn't registered yet, imports *module* (default: *name*), which
    registers it. Raises ``ImportError`` that names the module when it isn't
    installed, or when importing it didn't register the backend.
    """
    if _find(kind, name) is None:
        _import_registering(kind, name, module or name)
    required = _required.setdefault(kind, [])
    if name not in required:
        required.append(name)


def _import_registering(kind, name, module):
    try:
        __import__(module)
    except ImportError as exc:
        raise ImportError(
            "%s backend %r needs the module %r, which could not be imported (%s). "
            "Install the package that provides it." % (kind, name, module, exc)
        )
    if _find(kind, name) is None:
        raise ImportError(
            "importing %r did not register a %s backend named %r" % (module, kind, name)
        )


def _usable(entry):
    probe = entry[2]
    if probe is None:
        return True
    try:
        return bool(probe())
    except Exception:
        # a probe that blows up has no business stopping auto from trying the next one
        return False


def candidates(kind, override=None):
    """Yield ``(name, spec, builtin)`` for each backend to try, in search order.

    *override* is a name the user gave (usually from the environment). It is
    the only candidate, its probe is not consulted, and an unregistered name
    is imported as a module, the way ``require`` would.
    """
    if override:
        entry = _find(kind, override)
        if entry is None:
            _import_registering(kind, override, override)
            entry = _find(kind, override)
        yield entry[0], entry[1], entry[3]
        return
    tried = []
    for name in _required.get(kind, ()):
        entry = _find(kind, name)
        tried.append(name)
        if entry is not None and _usable(entry):
            yield entry[0], entry[1], entry[3]
    for entry in list(_entries.get(kind, ())):
        if entry[3] and entry[0] not in tried and _usable(entry):
            yield entry[0], entry[1], entry[3]


def load(spec):
    """Import and return what *spec* names: ``"module:Class"``, or a module."""
    module, _, attr = spec.partition(":")
    __import__(module)
    obj = sys.modules[module]
    if attr:
        for part in attr.split("."):
            obj = getattr(obj, part)
    return obj

