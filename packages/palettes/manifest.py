"""Freeze the palettes package from its canonical source tree.

A firmware build that wants palettes frozen includes this file from its own
freeze manifest -- micropython-pydevices' ``build_mp.py --modules palettes``
does exactly that.
"""

if 0:

    def package(*args, **kwargs):
        pass

    def module(*args, **kwargs):
        pass


package("palettes", base_path="./lib", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
