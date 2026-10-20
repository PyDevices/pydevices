# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Where apps keep their files: the data root, and a folder per app under it.

The data root is one setting for the whole program. Each app's folder is
``<root>/<app>``, made on first use. The launcher's restart file lives in
the root too. By default the root is:

==============  ==========================================================
Linux           ``$XDG_DATA_HOME/appkit``, or ``~/.local/share/appkit``
Windows         ``%LOCALAPPDATA%\\appkit``
macOS           ``~/Library/Application Support/appkit``
a board         ``/data``
the browser     ``/data``
==============  ==========================================================

``appkit.run(data_root=...)``, the same argument to ``Shell`` or
:func:`set_root` moves it everywhere. Without one, ``APPKIT_DATA`` moves it
on a desktop.
"""

import sys

#: Platforms that are a desktop operating system, whatever the interpreter.
DESKTOPS = ("linux", "darwin", "win32", "cygwin", "freebsd", "openbsd", "netbsd")

_root = None


def desktop(platform=None, implementation=None):
    """True on a desktop operating system (CPython, or MicroPython's unix or
    Windows port), False on a board or in the browser."""
    platform = platform or sys.platform
    implementation = implementation or sys.implementation.name
    if platform in ("webassembly", "emscripten", "wasi"):
        return False
    if implementation == "cpython":
        return True
    return platform in DESKTOPS


def _getenv(name):
    import os

    getenv = getattr(os, "getenv", None)  # boards have none
    if getenv is None:
        return None
    try:
        return getenv(name) or None
    except Exception:
        return None


def default_root(platform=None, implementation=None, getenv=None):
    """The data root this host uses when nothing sets one.

    *platform*, *implementation* and *getenv* stand in for ``sys.platform``,
    ``sys.implementation.name`` and ``os.getenv``, to ask about another host.
    """
    platform = platform or sys.platform
    if getenv is None:
        getenv = _getenv
    if not desktop(platform, implementation):
        return "/data"
    explicit = getenv("APPKIT_DATA")
    if explicit:
        return explicit
    if platform == "win32":
        base = getenv("LOCALAPPDATA")
        if not base:
            base = (getenv("USERPROFILE") or ".") + "\\AppData\\Local"
        return base + "\\appkit"
    home = getenv("HOME") or getenv("USERPROFILE") or "."
    if platform == "darwin":
        # Untested: macOS is community-supported.
        return home + "/Library/Application Support/appkit"
    base = getenv("XDG_DATA_HOME") or home + "/.local/share"
    return base + "/appkit"


def root():
    """The data root: what :func:`set_root` set, else :func:`default_root`."""
    return _root if _root is not None else default_root()


def set_root(path):
    """Move the data root for the whole program; None goes back to the default."""
    global _root
    if path is not None:
        path = str(path)
        while len(path) > 1 and path[-1] in "/\\" and not path.endswith(":\\"):
            path = path[:-1]
    _root = path


def join(base, *parts):
    """*base* and *parts* joined with the separator *base* already uses."""
    sep = "\\" if ("\\" in base and "/" not in base) else "/"
    out = base
    for part in parts:
        if out and out[-1] in "/\\":
            out += part
        else:
            out += sep + part
    return out


def _exists(path):
    import os

    try:
        os.stat(path)
        return True
    except OSError:
        return False


def makedirs(path):
    """Make folder *path* and any parents it needs; fine if it exists.

    ``os.makedirs`` for MicroPython, which has only ``os.mkdir``.
    """
    import os

    if _exists(path):
        return path
    # Every prefix, shortest first: "/a", "/a/b", ... or "C:\\a", "C:\\a\\b".
    prefixes = []
    for i in range(1, len(path)):
        if path[i] in "/\\" and path[i - 1] not in "/\\:":
            prefixes.append(path[:i])
    prefixes.append(path)
    for p in prefixes:
        if not _exists(p):
            try:
                os.mkdir(p)
            except OSError:
                pass  # made meanwhile, or a drive or root we can't make
    if not _exists(path):
        raise OSError("could not make the folder %r" % (path,))
    return path


def app_dir(name, base=None):
    """App *name*'s folder under *base* (default: the data root), made if missing."""
    return makedirs(join(base if base is not None else root(), name))
