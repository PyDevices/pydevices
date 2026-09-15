# Portable audio

## One name, one return type

There are three audio roles, and each always hands back the same kind of
object — on a board, on a desktop, everywhere:

| Role | Returns | You have | You want |
|---|---|---|---|
| `pcm_out(format=None, …)` | `PCMOutput` | PCM bytes | to `write()` them |
| `pcm_in(format=None, …)` | `PCMInput` | nothing | to `readinto()` |
| `audio_out(format=None, …)` | `AudioOut` | a sample graph | to `play()` it |

There is deliberately **no `audio_in`**. Playback has a player layer above raw
PCM; capture has none, and audioif has no input-side node to give it one. A
name implying otherwise would be the vagueness that caused the bug below.

This used to be inconsistent, and it cost real code. `audiodev.auto.audio_out`
returned a raw `PCMOutput` while `board_peripherals.audio_out` returned an
`AudioOut` wrapping one, so an app that could reach either factory could not
know what it was holding and wrote:

```python
pcm = audio_out(FMT, latency="low")
pcm = getattr(pcm, "transport", pcm)     # which one did I get?
```

Now it writes `pcm_out(FMT, latency="low")` and gets a `PCMOutput`. Note that
`pcm_out` also needs no audioif in firmware — nothing pulls a sample graph —
which is what lets a headless Connect speaker or a USB sound card run on a
build with no DSP package in it.

**Host or board** is resolved by `boarddev`, not by `audiodev` (which must stay
usable with no pydevices board tree at all):

```python
from boarddev import pcm_out
pcm = pcm_out(AudioFormat(44100, 2, 16), latency="low")
```

It resolves to `board_peripherals`, never `board_config` — importing that on
the ESP32-P4 starts MIPI DSI and stalls the VM, and a headless audio app has
no use for a display.

## What a board will accept

A board publishes an `AudioCapability` as `AUDIO_OUT` / `AUDIO_IN`, and
`audiodev.negotiate()` decides. Boards declare facts; they do not write
validation code.

```python
AUDIO_OUT = AudioCapability(
    AudioFormat(24000, 1, 16),   # default when format=None
    rates=None,                  # None = continuous (an I2S PLL); or a tuple
    channels=(1, 2),             # slot counts the WIRE will open
    native_channels=1,           # signals that reach a transducer
    bits=(16,),
    wire=I2SWire(0, sck=12, ws=10, sd=9, mck=13),
)
```

`channels` and `native_channels` are not the same thing, and conflating them
is a bug. The ESP32-P4's ES8311 clocks **two** slots into **one** speaker, so
44.1 kHz stereo opens `I2S.STEREO` and nothing is mixed down. A board that
could not say this would have to either refuse stereo or remix it needlessly.

`negotiate` raises rather than substituting. A silently-different format
sounds like working audio at the wrong pitch, which is the kind of bug nobody
notices until it ships.

`capability.wire` is for the third kind of consumer: one that opens the
peripheral itself and wants no Python device at all. usbif's C FreeRTOS pump
(`soundcard.py`) is the live example.

## Channel conversion

When a board's wire genuinely cannot take the requested channel count,
`negotiate` says so and `adapt_channels()` bridges 1↔2. The conversion lives
in `audiodev` — it is PCM byte work, the same kind `_scale_pcm` already does
for software volume — but **`audiodev` imports no audioif**, so the default
implementation is pure Python: correct everywhere, and slow.

A caller with audioif passes the C one in:

```python
from audiodev.accel import best_remix
pcm = adapt_channels(pcm, fmt, remix=best_remix())
```

`audiodev/__init__.py` and every transport backend import no audioif at all;
only `sample_out.py` and `accel.py` may. A test asserts this by walking the
AST, because the rule was broken once without anyone noticing.

## Directions

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
[`docs/board-peripherals.md`](board-peripherals.md): CP boards have no `board_peripherals.py`). Same
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
[`sdl2_audio.py`](../lib/audiodev/sdl2_audio.py)). So playback flows only while something calls
`AudioOut.service()` — the app tick, an `asyncio` pump, or `attach(app)` —
same requirement every queued transport already has. **No resampling**: a
sample's own `sample_rate` is not renegotiated against the transport; a
mismatch plays at the wrong pitch rather than raising, exactly like real DAC
hardware and exactly like CircuitPython's own `AudioOut`/`I2SOut`.

Raw PCM streaming is a role of its own, not an escape hatch through this one:
call `pcm_out()` and get a `PCMOutput` — `write`, `drain`, `awrite`, `adrain`,
volume/mute, `codec`. `AudioOut.transport` still exposes the same object, but
reaching through it means constructing an `AudioOut` (and therefore requiring
audioif) for a path that never plays a sample.

## Capture and tones

`pcm_in` returns a `PCMInput` (`readinto`/`areadinto`); tone/buzzer roles
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
needed. See [`tests/test_audiodev.py`](../tests/test_audiodev.py).

## ESP32-P4 status

The Waveshare ESP32-P4 configuration uses one half-duplex session for its I2S
peripheral and ES8311. Playback exposes hardware DAC volume/mute and controls
the speaker amplifier through `AudioOut`; capture exposes hardware ADC gain.
Register, stream, session, and GPIO behavior is covered by host simulations.
