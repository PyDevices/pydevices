## Unreleased

`audiodev` plays through the audio pump, and on a board it goes through
`audiobusio.I2SOut`.

**Nothing changes for you.** `audio_out(...)` still hands back an `AudioOut`,
`play(sample)` still plays it, `pcm_out(...)` still hands back a `PCMOutput`
you `write()` to. On a firmware without the pump every byte is the one the
old path produced.

- **`AudioOut` hands the graph to the pump where the firmware carries one.**
  A C thread the interpreter is not on pulls every block — a pinned FreeRTOS
  task on esp32, a `pthread` on a desktop — so your tick stops being what
  keeps the sound alive. Nothing asks for it and no board config opts in. A
  RawSample, a RawSample through an Overdrive, a Synthesizer and a WaveFile
  give the same digest on the old path, on the pump, and on a build with no
  `audiopump` at all: `e0c42e66584d6178`, `26e5bd8c0e8fc086`,
  `50ed7cc0ffce8279`, `aac53cd39e17dbdd`.
- **`lib/audiodev/pump.py` is new** — one module-level `Pump` reached through
  `pump.owner()`, three drivers (`BusioDriver` on esp32, `RingDriver` on unix,
  `ServiceDriver` where there are no threads), `Prefetch` for file-backed
  samples, and `attach_stream()` for raw PCM beside whatever is sounding. One
  client is the pump's tail directly; a second gets a root `audiomixer.Mixer`,
  a voice each at level 1.0, and a retarget. The mixer **sums**, so two loud
  clients clip. `loop` belongs to the client and travels with every swap.
- **On a board there is one way this firmware plays a sample:**
  `AudioOut → Pump → BusioDriver → audiobusio.I2SOut`. `audiodev`'s ESP32
  backend opens no channel, names no DMA size and never touches
  `machine.I2S`. That closes a defect by deletion: it used to open with
  `dma_frame=128` **fixed at every rate**, 16 ms of descriptor at 8 kHz
  against 2.7 ms at 48 kHz, and `I2SOut` sizes it `rate / 200`. What stays
  here is the policy — codec rails and volume, the root mixer, `Prefetch`,
  and the fault sentence.
- **A scheduled tick cannot land in the middle of a rearrangement.** On esp32
  a service tick arrives through `micropython.schedule`, between the
  interpreter's own bytecodes; landing one inside `stop()` finds a player
  that reads like a healthy old-path player and opens `machine.I2S` on the
  port the pump has just released — the drum machine's kit change falling off
  the audio clock with "Peripheral in use". Two guards, both live: a
  per-player `_pumping` flag across `play()` and `stop()`, and a pump-level
  latch around the global rearrangement. Proved by injecting a service tick at
  **every one of the 427 lines of a `play()`**, and at every line of `stop`,
  `close`, `pause` and `attach_stream`.
- **The desktop pump gives the interpreter its time back.** The engine's
  output ring makes the pump wait instead of dropping a block, so the driver
  has stopped parking it. On the **desktop unix build**, with an app doing
  3.5 ms of work a tick: **52 ms per 10 s on audio against 862 ms on the old
  path**, where the parked pump cost 923. With no app work the two are level
  (758 against 713). A live event lands **32.0 ms** later as a ceiling —
  exactly the ring depth — where the parked pump averaged 26.7 ms and spread
  to 69. A WAV plays back byte-identically 10 times out of 10 with all eight
  cores busy, overflow 0 by construction; with the drop planted back, 0 of 10.
  A parked pump used to spin 94 % of a core and now sleeps at 1 %.
- **A fault is a sentence**, not a traceback: `audiodev: the audio pump would
  not start — …`, and playback continues on the old path. A board whose
  config predates `wire=` used to fall back to `machine.I2S` in silence, which
  looks exactly like a working board; it says so once now.
- **`board_peripherals.py` for the Waveshare ESP32-P4 publishes `wire=` and
  `audio_power=`** on its PCM device, so the pump can bring the codec up
  without opening a stream. On a firmware without the pump both are inert.
  **It is the only board config that does**; every other I2S board keeps the
  old path and says so once.
- **Tests, where there were none.** `pump.py` had no test in this repository
  at all — CI's only contact with it was a layering rule and a line in a
  manifest. 35 now: 32 in `tests/test_pump.py` against stand-ins and 3 in
  `tests/test_pump_interpreter.py` that drive a real MicroPython build, which
  skip loudly where there is no interpreter (`PYDEVICES_REQUIRE_PUMP=1` turns
  the skip into a failure). Sixteen planted faults, all caught.
- **`.github/workflows/tests.yml` gains a `pump` job** that builds a unix
  MicroPython with `PyDevices/audioif` as a user C module and runs the
  interpreter tests against it. It needs audioif and nothing else: the
  platform driver is a separate repository and is optional, and without one
  the same loop runs on the interpreter's own thread.
- `lib/audiodev/pump.py` was missing from the generated
  `pydevices-desktop.toml`, which failed the unit suite and the whole
  `validate-pyscript-filesystem-toml` workflow at once — a PyScript desktop
  install fetched every `audiodev` module except the pump. Regenerated with
  the org generator, not hand-edited.

**What has not run on a board.** `audiodev` on `audiobusio` is a desktop
build, a link map, and the sink path it replaced; two ESP32 images are staged
and unflashed. `MP3Decoder` has never been through the pump. Nothing has
measured what a retarget costs. `Pump._retarget()`'s live branch has no test
of its own, and `AudioOut.play`'s latch and `Pump.play`'s `try`/`finally`
survived their planted faults, so they are argued rather than proved.

The **previous** ESP32 backend did run, on the Waveshare ESP32-P4 panel:
`play()` in 8 ms, 100 of 100 stop/play cycles, and `service()` at 95 µs mean
against the old path's 234 µs.

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

