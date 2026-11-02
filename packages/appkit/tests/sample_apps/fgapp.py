# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""An app whose foreground function is a plain function in this module.

``step`` is referenced by the foreground loop, and its globals are this
module's namespace, which holds ``main``. It waits a little, so a timer can
close the app while the call is in progress: the call itself must not keep
the module alive after close().
"""

state = {"frames": 0}


def step():
    import multimer

    state["frames"] += 1
    multimer.sleep_ms(30)


def main(scope):
    scope.foreground(step)
