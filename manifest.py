"""Package the PyDevices source tree for installation.

Target paths are ``lib/...`` and ``utils/...``, so installing with ``target="."``
lays the tree out the way the documented search paths expect::

    MICROPYPATH=".:.frozen:lib:utils:~/.micropython/lib:/usr/lib/micropython"
    PYTHONPATH=".:lib:utils"

``lib`` holds the importable packages (``appdev``, ``audiodev``, ``displaydev``,
``multimer``) and the flat modules beside them; ``utils`` holds the host-side
helpers, including the portable ``mip.py`` that stands in for firmware ``mip``
on CPython, CircuitPython and Pyodide. Keeping ``utils`` *after* ``.frozen``
matters: MicroPython ships ``mip`` in firmware, and ``utils/mip.py`` raises
ImportError if the search order ever lets it shadow that.

Note this is not a freeze manifest -- the target paths are prefixed, so frozen
modules would import as ``lib.appdev`` rather than ``appdev``. Nor does the
org's interpreter build freeze this tree: hosts install it with ``mip``, so
what runs is always the published or staged code, never a build-time snapshot.
"""

if 0:

    def package(*args, **kwargs):
        pass

    def module(*args, **kwargs):
        pass


package("lib", base_path=".", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
package("utils", base_path=".", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
