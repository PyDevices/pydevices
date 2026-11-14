# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""vtterm's tests, runnable on MicroPython, CircuitPython and CPython.

    python packages/vtterm/tests/run.py           # from the repo root, or
    micropython packages/vtterm/tests/run.py
    circuitpython packages/vtterm/tests/run.py

The tests are plain functions named ``test_*``. vtterm and palettes come from
this checkout, ahead of any frozen copy; pygraphics comes from the
interpreter (``pip install pydevices-pygraphics`` on CPython).
pytest collects ``test_all`` from here too.
"""

import sys

try:
    _HERE = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
except NameError:
    _HERE = "."
for _path in (_HERE + "/../../palettes/lib", _HERE + "/..", _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

MODULES = ("test_screen", "test_render", "test_keys", "test_console")


def _run():
    """Run every test, print each failure, and return how many failed."""
    failed = passed = 0
    for name in MODULES:
        mod = __import__(name)
        for attr in sorted(dir(mod)):
            if not attr.startswith("test_"):
                continue
            try:
                getattr(mod, attr)()
                passed += 1
            except Exception as e:  # noqa: BLE001 -- report every failure, keep going
                failed += 1
                print("FAIL %s.%s: %r" % (name, attr, e))
                if hasattr(sys, "print_exception"):
                    sys.print_exception(e)
                else:
                    __import__("traceback").print_exc()
    print("%d passed, %d failed" % (passed, failed))
    return failed


def test_all():
    """Every test passes."""
    failed = _run()
    assert not failed, "%d vtterm tests failed" % failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
