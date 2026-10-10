# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run on MicroPython: does the nrf timer interrupt's callback run the call it
schedules before it returns?

It must not. The VM runs pending scheduled calls at every jump, and on nrf the
port calls ``_nrf_hard`` from the interrupt, so a jump inside it would run the
whole delivery inside the interrupt. Prints ``inside: N after: M``.
"""

import sys


class _Timer:
    ONESHOT = 0

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def deinit(self):
        pass


class _Machine:
    Timer = _Timer


sys.modules["machine"] = _Machine
sys.path.insert(0, sys.argv[1])

import multimer._src_machine as src  # noqa: E402

ran = []
src._nrf_soft_cb = lambda _t: ran.append(1)
src._nrf_hard(None)
inside = len(ran)
for _ in range(3):  # jumps: the scheduled call may run now
    pass
print("inside:", inside, "after:", len(ran))
