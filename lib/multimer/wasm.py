# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""WebAssembly software Timer using JS setTimeout/setInterval."""

from . import _provider_pump, _provider_sleep_ms
from ._core import _TimerCore
from ._schedule import schedule

try:
    import _wasm_bridge
except ImportError:
    _wasm_bridge = None

name = "wasm"
uses_interrupts = False
is_async = False
_defer_sync_arm = False


def pump():
    _provider_pump()


def sleep_ms(ms):
    _provider_sleep_ms(ms)


__all__ = ["Timer", "is_async", "name", "pump", "sleep_ms", "uses_interrupts"]


class Timer(_TimerCore):
    def __init__(self, id=-1, **kwargs):
        self._timer_id = None
        self._scheduled_deliver = self._run_deliver
        super().__init__(id, **kwargs)

    def _arm(self):
        if _wasm_bridge is None:
            return
        if self._mode == self.ONE_SHOT:
            self._timer_id = _wasm_bridge.set_timeout(self._on_tick, self._period_ms)
        else:
            self._timer_id = _wasm_bridge.set_interval(self._on_tick, self._period_ms)

    def _disarm(self):
        if self._timer_id is not None and _wasm_bridge is not None:
            _wasm_bridge.clear_timer(self._timer_id)
            self._timer_id = None

    def _on_tick(self):
        # We bounce through the soft scheduler so we don't execute app code
        # from directly inside the JS event callback, preventing reentrancy
        # issues or locking up the browser thread.
        schedule(self._scheduled_deliver, self)

    def _run_deliver(self, _arg):
        self._deliver()
