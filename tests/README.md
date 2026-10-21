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
| [`test_display_driver.py`](test_display_driver.py) | `DisplayDriver` base class |
| [`test_fbdisplay.py`](test_fbdisplay.py) | `FBDisplay` on a fake framebuffer |
| [`test_autodisplay.py`](test_autodisplay.py) | `displaydev.auto` host selection |
| [`test_backends.py`](test_backends.py) | the `backends` registry (register, require, probes, env override) and `AutoDisplay` / `audiodev.auto` searching it |
| [`test_displaydev_auto.py`](test_displaydev_auto.py) | backends must not import `displaydev.auto` |
| [`test_displaydev_lifecycle.py`](test_displaydev_lifecycle.py) / [`test_displaydev_capabilities.py`](test_displaydev_capabilities.py) | quit lifecycle and `capabilities()` |
| [`test_displaydev_fps.py`](test_displaydev_fps.py) | frame-rate meter: nothing wrapped while off, frames/present/busy counted while on, `flush_rect` as flushes not frames, the appdev refresh calling a wrapper installed late |
| [`test_color.py`](test_color.py) / [`test_byteswap.py`](test_byteswap.py) / [`test_desktop_scale.py`](test_desktop_scale.py) | displaydev helpers |
| [`test_env.py`](test_env.py) | `boarddev`'s environment helpers, and that `displaydev` no longer carries them |
| [`test_needs_refresh.py`](test_needs_refresh.py) / [`test_backend_isolation.py`](test_backend_isolation.py) | backend flags and imports |
| [`test_jndisplay_scroll.py`](test_jndisplay_scroll.py) | JNDisplay scroll (needs IPython + Pillow) |
| [`test_pgdisplay_frame_recorder.py`](test_pgdisplay_frame_recorder.py) | frame-recorder surface |
| [`test_multimer.py`](test_multimer.py) | public multimer API |
| [`test_events.py`](test_events.py) / [`test_keys.py`](test_keys.py) | shared event types and key codes |
| [`test_boarddev.py`](test_boarddev.py) | `boarddev.bind_lazy` |
| [`test_mdns.py`](test_mdns.py) | `mdns.py` (pydevices-desktop): CircuitPython's `mdns` API over python-zeroconf, its errors, and, with zeroconf installed, a service advertised and found on the machine's own network |
| [`test_wifi.py`](test_wifi.py) | `wifi.connect_from_secrets()` counts a board as connected only with a link, so a static address joins at boot and rejoins after a drop |
| [`test_standalone.py`](test_standalone.py) | displaydev and multimer import in isolation |
| [`test_mip_portable.py`](test_mip_portable.py) | portable [`utils/mip.py`](../utils/mip.py) |
| `test_audiodev*.py`, `test_*_audio.py`, [`test_auto.py`](test_auto.py) | audiodev (see audio README) |
| [`test_portability.py`](test_portability.py) / [`test_contract_proof.py`](test_contract_proof.py) | portable-module constraints |
| [`test_bledev.py`](test_bledev.py) | runs [`bledev_contract.py`](bledev_contract.py) on CPython and unix MicroPython, and proves five planted faults fail it (see [docs/bledev-internals.md](../docs/bledev-internals.md#the-checks)) |
| [`test_ssd1306.py`](test_ssd1306.py) / [`test_oled_drivers.py`](test_oled_drivers.py) | the one-bit and grayscale OLED drivers on recording fake buses: `test_oled_drivers.py` runs [`oled_contract.py`](oled_contract.py) (SH1106, SH1107, SSD1305, SSD1322, SSD1325, SSD1327, checked against each datasheet's command set) on CPython and unix MicroPython, and proves five planted faults fail it |
