"""setTimeout/setInterval timer provider for direct WebAssembly."""

import _wasm_bridge

from . import _provider_pump
from ._core import _TimerCore

_active = {}
_next_id = 1
name = "wasm"
uses_interrupts = True
is_async = False
_defer_sync_arm = False


class Timer(_TimerCore):
    def __init__(self, id=-1, **kwargs):
        global _next_id
        if id < 0:
            id = _next_id
            _next_id += 1
        super().__init__(id, **kwargs)

    def _arm(self):
        _active[self.id] = self
        _wasm_bridge.timer_start(
            self.id, self._period_ms, self._mode == self.PERIODIC, self._deliver
        )

    def _disarm(self):
        _wasm_bridge.timer_cancel(self.id)
        _active.pop(self.id, None)


def _backend_drain():
    while True:
        timer_id = _wasm_bridge.timer_poll()
        if timer_id is None:
            return
        timer = _active.get(timer_id)
        if timer is not None:
            timer._deliver()


def pump():
    _provider_pump(_backend_drain)


def sleep_ms(ms):
    _provider_pump(_backend_drain)
    _wasm_bridge.sleep_ms(max(0, int(ms)))
    _provider_pump(_backend_drain)


__all__ = ["Timer", "is_async", "name", "pump", "sleep_ms", "uses_interrupts"]
