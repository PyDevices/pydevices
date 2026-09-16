## v0.4.0 (2026-09-16)

Breaking: the audio roles are renamed, and `audio_in` is removed.

- Audio roles are `pcm_out` (-> `PCMOutput`), `pcm_in` (-> `PCMInput`) and
  `audio_out` (-> `AudioOut`). One name, one return type, on boards and hosts
  alike. Previously `audiodev.auto.audio_out` returned a raw transport while
  `board_peripherals.audio_out` returned a sample player, so callers could not
  know what they held and wrote `getattr(pcm, "transport", pcm)`.
- There is no `audio_in`. Output has a player layer above raw PCM; capture does
  not, so a name implying one was misleading. Use `pcm_in`.
- `audiodev.auto` renames follow: `audio_out` -> `pcm_out`,
  `sample_audio_out` -> `audio_out`. `AutoAudio` is gone. Backend modules
  rename `audio_out`/`audio_in` to `pcm_out`/`pcm_in`; `pwm_tone` exposes
  `tone_out`, because it returns a `ToneOutput`.
- Boards declare an `AudioCapability` and `audiodev.negotiate()` decides,
  replacing each board's hand-written format validation. `channels` (what the
  wire opens) is separate from `native_channels` (what reaches a transducer):
  a mono speaker fed by a two-slot wire needs no mixdown.
- `I2SWire` publishes port and pin numbers on the capability, so a consumer
  that drives the peripheral itself stops reaching into board-private names.
- `adapt_channels`/`ChannelAdapter` convert 1<->2 channels with an injectable
  implementation; `audiodev.accel.best_remix()` supplies the C one where
  audioif is present. `audiodev/__init__.py` and every transport import no
  audioif, and a test asserts it.
- The portable remix indexes bytes directly instead of calling `struct` per
  sample: 2.9x faster with no allocation. Measured on an ESP32 at 240 MHz, a
  10 ms chunk of 44.1 kHz stereo went from 50.5 ms to 17.3 ms.
- `boarddev.pcm_out`/`pcm_in`/`audio_out` resolve host-vs-board, importing
  `board_peripherals` and never `board_config`.
- `PaceOutput`/`pace_output` and `PCMOutput.try_write` land from the P4 work:
  `machine.I2S` is armed non-blocking, so a raw sink must be paced or
  `write()` raises once DMA fills.
- Every board converted: five I2S boards, five host shims, and the PWM buzzer
  boards (`kind="tone"`, which take no format).
- New `board_configs/nodisplay/` for boards that are only peripherals; first
  occupant is the QT Py ESP32 Pico with an Adafruit Audio BFF.
- ESP32-P4: `audio_power` brings the codec up without opening an I2S stream,
  for a consumer (usbif's C pump) that opens the peripheral itself.

## v0.3.8 (2026-08-29)

- docs: link pass over docs/ and README
- Regenerate the ecosystem map (workbench, micropython-vst3, overlay fixes)
- Adopt publishing-v6 (MIP second-publication race fix)
- sdldisplay: ignore synthetic WINDOWEVENT_CLOSE under headless drivers
- requirements: drop pydevices-usdl2/-uwin32 - registered names with no releases
- Golden probe: prime the output before starting the mixer voice
- Producer script and hardening for interpreter release assets
- Record exec mode on fetch_interpreters.sh and wasm.py
- Regenerate the ecosystem map (audioif blurb, micropython-pydevices)
- Distribute interpreter binaries as release assets, not git content

