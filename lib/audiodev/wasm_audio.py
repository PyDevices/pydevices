"""Web Audio PCM backend for the direct MicroPython WebAssembly runtime."""

import _wasm_bridge

from audiodev import AudioFormat, PCMInput, PCMOutput, check_latency

DEFAULT_FORMAT = AudioFormat(48000, 2, 16, signed=True, byteorder="little")


def _format_args(fmt):
    return (fmt.rate, fmt.channels, fmt.bits, fmt.signed, fmt.byteorder == "big")


class WasmPCMOutput(PCMOutput):
    def __init__(self, format=DEFAULT_FORMAT, *, latency=None, **kwargs):
        check_latency(latency)
        self.latency = latency
        super().__init__(format, **kwargs)

    def _open(self):
        if not _wasm_bridge.audio_state(False):
            raise RuntimeError(
                "audio output is disabled; use the host Enable Audio control"
            )

    def _write(self, buf):
        return _wasm_bridge.audio_write(buf, *_format_args(self.format))

    def _drain(self):
        while self.queued_size():
            _wasm_bridge.sleep_ms(1)

    def queued_size(self):
        return _wasm_bridge.audio_queued_size(False)

    def is_active(self):
        return self.queued_size() > 0

    def clear(self):
        _wasm_bridge.audio_clear(False)


class WasmPCMInput(PCMInput):
    def __init__(self, format=DEFAULT_FORMAT, *, latency=None, **kwargs):
        check_latency(latency)
        self.latency = latency
        super().__init__(format, **kwargs)

    def _open(self):
        if not _wasm_bridge.audio_state(True):
            raise RuntimeError(
                "microphone is disabled; use the host Enable Microphone control"
            )

    def _readinto(self, buf):
        return _wasm_bridge.audio_readinto(buf, *_format_args(self.format))

    def queued_size(self):
        return _wasm_bridge.audio_queued_size(True)

    def is_active(self):
        return self.queued_size() > 0

    def clear(self):
        _wasm_bridge.audio_clear(True)


def audio_out(format=None, **kwargs):
    return WasmPCMOutput(format or DEFAULT_FORMAT, **kwargs)


def audio_in(format=None, **kwargs):
    return WasmPCMInput(format or DEFAULT_FORMAT, **kwargs)
