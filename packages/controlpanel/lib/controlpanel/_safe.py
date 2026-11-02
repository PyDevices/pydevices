# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Keep an exception from escaping into LVGL.

On MicroPython, a callback that raises leaves the binding's re-entrancy
count raised, and from then on LVGL's timers quietly stop. Every callback
the panel gives LVGL goes through ``safe``: the error is printed and the
panel carries on.
"""

import sys


def safe(fn):
    def wrapper(*args):
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001
            printer = getattr(sys, "print_exception", None)
            if printer is not None:
                printer(exc)
            else:
                import traceback

                traceback.print_exception(type(exc), exc, exc.__traceback__)
        return None

    return wrapper
