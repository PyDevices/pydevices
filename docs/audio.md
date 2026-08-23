# Portable audio

The audio surface is split by direction: boards expose `audio_out` and/or
`audio_in`. Each object is a subclass of `audiodev.PCMOutput`, `PCMInput`, or
`ToneOutput`. It reports an `AudioFormat` plus a `capabilities` set. PCM output
supports `write`, `drain`, `awrite`, and `adrain`; PCM input supports `readinto`
and `areadinto`. Volume, gain, and mute use a normalized 0–100 scale and select
hardware controls when a codec provides them, otherwise `audiodev` scales PCM in
software.

Queued hosts also implement `service()`, `queued_size()`, `is_active()`, and
`clear()` on the device (no-ops on MCU). Call `service()` from the app tick.

Codec-specific features remain reachable through `device.codec`. Shared
half-duplex hardware uses `AudioSession`; opening the opposite direction while
one direction owns the session raises `OSError`.

## Host backends

`audiodev.sdl2_audio` is the reference playback and real-microphone backend for
MicroPython and CPython. It uses queued SDL audio and provides the same sync and
async contract as hardware devices.

`audiodev.pygame_audio` provides CPython playback and capture for pygame-ce hosts
(typically Windows / `python.exe`). Playback uses pygame's bundled SDL via
`SDL_QueueAudio`; capture uses `pygame._sdl2.AudioDevice` (`iscapture=True`).

`audiodev.web_audio` provides PyScript / browser playback (`AudioContext`) and
capture (`getUserMedia`).

`audiodev.wasm_audio` is the direct MicroPython WebAssembly backend. The
compiled bridge owns Web Audio and permission state, while Python sees only
neutral PCM buffers and queue operations. It supports mono/stereo 8-, 16-, and
32-bit signed or unsigned samples in either byte order at caller-selected
rates. A host page must explicitly enable audio or microphone access first.

Desktop `board_peripherals` may use `audiodev.auto` for host probe. Fixed host boards
import a concrete backend. `audiodev` itself does not import `displaydev`.

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

## ESP32-P4 status

The Waveshare ESP32-P4 configuration uses one half-duplex session for its I2S
peripheral and ES8311. Playback exposes hardware DAC volume/mute and controls
the speaker amplifier; capture exposes hardware ADC gain. Register, stream,
session, and GPIO behavior is covered by host simulations.
