# Direct MicroPython WebAssembly

The direct browser runtime is a reproducible MicroPython v1.28.0 WebAssembly
variant built by the org's aggregator workspace. Its compiled `_wasm_bridge`
owns browser integration; Python never imports `js`, uses DOM proxies, or
receives browser objects.

The bridge provides:

- continuous RGB565 framebuffer painting through `requestAnimationFrame`;
- pointer, touch, pen, wheel, keyboard, gamepad, and focus input;
- Web Audio playback and capture with explicit permission state;
- one-shot and periodic browser timers with Python callback delivery; and
- Asyncify-backed Fetch used by frozen `requests` and `mip`.

The Python backends are `displaydev.wasmdisplay.WasmDisplay`,
`audiodev.wasm_audio`, and `multimer.wasm`. Their automatic selectors prefer
these providers only when `_wasm_bridge` imports successfully. The display
owns one RGB565 `bytearray`; the browser scans it each animation frame, so
there is no explicit present or double-buffer protocol.

[`bin/wasm.py`](../bin/wasm.py) (and [`bin/pyscript.py`](../bin/pyscript.py)) require `PyDevices.github.io`,
`pydevices-examples`, and `mip` checked out as siblings of this repository —
the host serves gallery content and MIP packages straight out of those
directories.

Run an application through the first-party gallery host with:

```bash
bin/wasm.py -m bouncing_balls
bin/wasm.py my_app.py
bin/wasm.py --no-open -m paint
```

The launcher only stages URL intent, serves the workspace, prints the URL, and
opens a browser. Playwright is maintained as a separate test harness.

Audio and microphone use require the host page's Enable Audio/Microphone
control. Backends raise a clear permission error until the relevant control
has been used.

Execution currently stays on the browser main thread. Moving the VM to a
worker is a future milestone, not part of this backend contract.
