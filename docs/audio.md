# Portable audio

The audio surface is split by direction: boards expose `audio_out` and/or
`audio_in`.

## Playback: the audiosample contract

`audio_out` returns an **`audiodev.sample_out.AudioOut`**: `play(sample,
loop=False)`, `stop()`, `pause()`, `resume()`, `playing`. `sample` is anything
satisfying CircuitPython's audiosample pull protocol — a
`synthio.Synthesizer`, an `audiomixer.Mixer`, an `audiocore.RawSample` /
`WaveFile`, or any effect chained on top of one (`audiofilters`,
`audiodelays`, `audiofreeverb`, `audiospeed`), all provided by the
`audioif` usermod on MicroPython or the separately installed
`pydevices-audioif` CPython distribution (`import synthio`,
`import audiomixer`, ...). CPython users install it from TestPyPI with:

```sh
python -m pip install --index-url https://test.pypi.org/simple/ pydevices-audioif
```

Neither `pydevices` distribution depends on it; importing `audiodev` and
using raw PCM transports therefore remain available without synthesis support.
This is the same object shape CircuitPython code already expects from
`audiobusio.I2SOut`/`audioio.AudioOut` — a synth built for a CircuitPython
tutorial runs unchanged against this port's `AudioOut`.

**On CircuitPython boards** (`board_configs/cp/`) the contract is satisfied
*natively*: there is no `audio_out` role or `AudioOut` wrapper at all — CP
apps construct `audiobusio.I2SOut(...)`/`audioio.AudioOut(...)` directly (see
`docs/board-peripherals.md`: CP boards have no `board_peripherals.py`). Same
protocol shape, zero adapter, because CircuitPython's own output devices
already speak it.

**On MicroPython**, `AudioOut` is a pure-Python pump wrapping a push-based
transport (below): it pulls PCM from the sample via
`audiocore.get_buffer()`/`reset_buffer()` on a lookahead schedule and pushes
it into the transport's `write()`. This is the only sound architecture here,
not a stopgap: every real backend's bottom layer is a push+queued transport
(`SDL_QueueAudio`, WASAPI, the wasm bridge, `machine.I2S.write`), and an
audio-thread callback into Python is unsafe even in C once it would need to
pull a synth's block graph, which allocates on the GC heap (documented in
`sdl2_audio.py`). So playback flows only while something calls
`AudioOut.service()` — the app tick, an `asyncio` pump, or `attach(app)` —
same requirement every queued transport already has. **No resampling**: a
sample's own `sample_rate` is not renegotiated against the transport; a
mismatch plays at the wrong pitch rather than raising, exactly like real DAC
hardware and exactly like CircuitPython's own `AudioOut`/`I2SOut`.

Low-level raw PCM streaming is still available as an escape hatch: every
`AudioOut.transport` is (or behaves like) a `PCMOutput` — `write`, `drain`,
`awrite`, `adrain`, volume/mute, `codec`. `audiodev.auto.audio_out()` returns
the bare transport for callers that want to push raw bytes without going
through the sample-pull layer at all.

## Capture and tones: unchanged

`audio_in` returns a `PCMInput` (`readinto`/`areadinto`); tone/buzzer roles
return a `ToneOutput` (`play(frequency, ...)`, frequency-based, not
sample-based — unrelated to `AudioOut.play(sample)` above). Both report an
`AudioFormat` plus a `capabilities` set; volume, gain, and mute use a
normalized 0–100 scale and select hardware controls when a codec provides
them, otherwise `audiodev` scales PCM in software.

Queued hosts also implement `service()`, `queued_size()`, `is_active()`, and
`clear()` on the device (no-ops on MCU).

Codec-specific features remain reachable through `device.codec`. Shared
half-duplex hardware uses `AudioSession`; opening the opposite direction while
one direction owns the session raises `OSError`.

## Host backends (transports under `AudioOut`, or usable raw)

`audiodev.sdl2_audio` is the reference playback and real-microphone backend for
MicroPython. It uses queued SDL audio and provides the same sync and
async contract as hardware devices.

`audiodev.win_audio` is the Windows WASAPI backend (`uwin32`), selected ahead
of `sdl2_audio` on Windows when available.

`audiodev.wasm_audio` is the direct MicroPython WebAssembly backend. The
compiled bridge owns Web Audio and permission state, while Python sees only
neutral PCM buffers and queue operations. It supports mono/stereo 8-, 16-, and
32-bit signed or unsigned samples in either byte order at caller-selected
rates. A host page must explicitly enable audio or microphone access first.

`audiodev.i2s_audio` adapts `machine.I2S` for MCU boards; boards construct it
directly with board-specific pins/codec wiring, then wrap it in `AudioOut`.

Desktop `board_peripherals` may use `audiodev.auto` for host probing. Fixed host boards import a
concrete backend. `audiodev` itself does not import `displaydev`.

### CPython and Pyodide sample playback

`audiodev.pygame_audio` (CPython + pygame-ce, via `SDL_QueueAudio` on
pygame's bundled SDL) and `audiodev.web_audio` (PyScript/Pyodide, via
`AudioContext`/`getUserMedia`) still exist and still work as raw
`PCMOutput`/`PCMInput` transports and can back `AudioOut` when
`pydevices-audioif` is installed. Automatic selection uses MicroPython wasm,
Pyodide Web Audio, Windows `uwin32`, `usdl2`, then pygame-ce, in that order.
Constructing `AudioOut` without `audiocore` fails immediately with the install
command above; direct raw `write()`/`readinto()` remains independent.

## Emulated devices (CI / no hardware)

`audiodev.emulated_audio` implements WAV files, a waveform generator, in-memory
loopback, and a discard sink. It is never auto-selected:

```python
from audiodev import AudioFormat
from audiodev.emulated_audio import audio_in, audio_out

fmt = AudioFormat(24000, 1, 16)
out = audio_out(fmt, path="/sd/prompt.wav")
out.write(pcm_bytes)
out.close()

mic = audio_in(path="/sd/prompt.wav")
```

`WavPCMOutput` doubles as the deterministic golden-file target for testing
the whole `AudioOut` chain — synthio/Mixer rendered through `AudioOut` over
`emulated_audio.audio_out(path=...)`, hash-compared, no audio hardware
needed. See `tests/test_audiodev.py`.

## ESP32-P4 status

The Waveshare ESP32-P4 configuration uses one half-duplex session for its I2S
peripheral and ES8311. Playback exposes hardware DAC volume/mute and controls
the speaker amplifier through `AudioOut`; capture exposes hardware ADC gain.
Register, stream, session, and GPIO behavior is covered by host simulations.
