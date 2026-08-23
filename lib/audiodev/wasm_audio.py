# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Browser WebAssembly backend for PyScript (:mod:`audiodev` PCM devices)."""

try:
    import asyncio
except ImportError:  # pragma: no cover
    try:
        import uasyncio as asyncio
    except ImportError:
        asyncio = None

import time
import uctypes
from audiodev import AudioFormat, PCMInput, PCMOutput, check_latency

try:
    import _wasm_bridge
except ImportError:
    _wasm_bridge = None


def _sleep_ms(milliseconds):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(milliseconds)
    else:
        time.sleep(milliseconds / 1000)


async def _asleep_ms(milliseconds):
    if hasattr(asyncio, "sleep_ms"):
        await asyncio.sleep_ms(milliseconds)
    else:
        await asyncio.sleep(milliseconds / 1000)


class WasmPCMOutput(PCMOutput):
    """Queued PCM playback via _wasm_bridge to AudioContext."""

    def __init__(self, fmt, *, poll_ms=4):
        if fmt.bits != 16 or not fmt.signed or fmt.byteorder != "little":
            raise ValueError("wasm_audio playback requires signed 16-bit little-endian PCM")
        super().__init__(fmt)
        self.poll_ms = int(poll_ms)
        self._is_open = False

    def _open(self):
        if self._is_open:
            return
        if _wasm_bridge is not None:
            _wasm_bridge.audio_out_open(self.format.rate, self.format.channels)
        self._is_open = True

    def _write(self, buf):
        if _wasm_bridge is not None:
            _wasm_bridge.audio_out_write(uctypes.addressof(buf), len(buf))
        return len(buf)

    async def _awrite(self, buf):
        await _asleep_ms(0)
        return self._write(buf)

    def _drain(self):
        if _wasm_bridge is not None:
            while _wasm_bridge.audio_out_queued_ms() > 0:
                _sleep_ms(self.poll_ms)

    async def _adrain(self):
        if _wasm_bridge is not None:
            while _wasm_bridge.audio_out_queued_ms() > 0:
                await _asleep_ms(self.poll_ms)

    def _close(self):
        if self._is_open and _wasm_bridge is not None:
            _wasm_bridge.audio_out_close()
        self._is_open = False


class WasmPCMInput(PCMInput):
    """Microphone capture via _wasm_bridge."""

    def __init__(self, fmt, *, poll_ms=4, queue_ms=500, samples=2048):
        if fmt.bits != 16 or not fmt.signed or fmt.byteorder != "little":
            raise ValueError("wasm_audio capture requires signed 16-bit little-endian PCM")
        if fmt.channels != 1:
            raise ValueError("wasm_audio capture requires mono PCM")
        super().__init__(fmt)
        self.poll_ms = int(poll_ms)
        self._is_open = False

    def _open(self):
        if self._is_open:
            return
        if _wasm_bridge is not None:
            _wasm_bridge.audio_in_open(self.format.rate)
        self._is_open = True

    def _readinto(self, buf):
        if _wasm_bridge is not None:
            while True:
                count = _wasm_bridge.audio_in_read(uctypes.addressof(buf), len(buf))
                if count > 0:
                    return count
                _sleep_ms(self.poll_ms)
        return len(buf)

    async def _areadinto(self, buf):
        if _wasm_bridge is not None:
            while True:
                count = _wasm_bridge.audio_in_read(uctypes.addressof(buf), len(buf))
                if count > 0:
                    return count
                await _asleep_ms(self.poll_ms)
        return len(buf)

    def _close(self):
        if self._is_open and _wasm_bridge is not None:
            _wasm_bridge.audio_in_close()
        self._is_open = False


def audio_out(format=None, *, latency=None, poll_ms=4):
    check_latency(latency)
    fmt = format or AudioFormat(24000, 1, 16)
    return WasmPCMOutput(fmt, poll_ms=poll_ms)


def audio_in(format=None, *, latency=None, poll_ms=4, queue_ms=500, samples=None):
    check_latency(latency)
    if samples is None:
        samples = 512 if latency == "low" else 2048
    fmt = format or AudioFormat(24000, 1, 16)
    return WasmPCMInput(
        fmt,
        poll_ms=poll_ms,
        queue_ms=queue_ms,
        samples=samples,
    )
