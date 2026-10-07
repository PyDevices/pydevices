# Tests

Stdlib `unittest` for packages that live in this repo: `displaydev`, `multimer`,
`events`, `keys`, `boarddev`, `audiodev`, `utils`, and related drivers.

[`_env.py`](_env.py) puts `lib/`, `utils/`, and `drivers/` on `sys.path`.

## Running

From the repository root:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v
```

Do not run audiodev tests while another process is playing audio — see
[lib/audiodev/README.md](../lib/audiodev/README.md#tests).

## What is covered

| Module | Area |
|--------|------|
| `test_display_driver.py` | `DisplayDriver` base class |
| `test_fbdisplay.py` | `FBDisplay` on a fake framebuffer |
| `test_autodisplay.py` | `displaydev.auto` host selection |
| `test_displaydev_auto.py` | backends must not import `displaydev.auto` |
| `test_displaydev_lifecycle.py` / `test_displaydev_capabilities.py` | quit lifecycle and `capabilities()` |
| `test_displaydev_fps.py` | frame-rate meter: nothing wrapped while off, frames/present/busy counted while on, `flush_rect` as flushes not frames, the appdev refresh calling a wrapper installed late |
| `test_env.py` / `test_color.py` / `test_byteswap.py` / `test_desktop_scale.py` | displaydev helpers |
| `test_needs_refresh.py` / `test_backend_isolation.py` | backend flags and imports |
| `test_jndisplay_scroll.py` | JNDisplay scroll (needs IPython + Pillow) |
| `test_pgdisplay_frame_recorder.py` | frame-recorder surface |
| `test_multimer.py` | public multimer API |
| `test_events.py` / `test_keys.py` | shared event types and key codes |
| `test_boarddev.py` | `boarddev.bind_lazy` |
| `test_wifi.py` | `wifi.connect_from_secrets()` counts a board as connected only with a link, so a static address joins at boot and rejoins after a drop |
| `test_standalone.py` | displaydev and multimer import in isolation |
| `test_mip_portable.py` | portable `utils/mip.py` |
| `test_audiodev*.py`, `test_*_audio.py`, `test_auto.py` | audiodev (see audio README) |
| `test_portability.py` / `test_contract_proof.py` | portable-module constraints |
| `test_bledev.py` | runs `bledev_contract.py` on CPython and unix MicroPython, and proves five planted faults fail it (see [docs/bledev-internals.md](../docs/bledev-internals.md#the-checks)) |
