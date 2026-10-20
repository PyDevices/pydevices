"""Freeze the pdwidgets package from its canonical source tree.

Discovered automatically by a workspace's aggregator manifests
(``manifest-micropython.py`` / ``manifest-circuitpython.py``), which include
``<repo>/manifest.py`` for every sibling checked out beside it.
"""

if 0:

    def package(*args, **kwargs):
        pass

    def module(*args, **kwargs):
        pass


package("pdwidgets", base_path="./lib", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
