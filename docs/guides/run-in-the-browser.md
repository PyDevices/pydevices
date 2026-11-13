# Direct MicroPython WebAssembly

The direct browser runtime is a reproducible MicroPython v1.28.0 WebAssembly
variant. Its compiled `_wasm_bridge`
owns browser integration; Python never imports `js`, uses DOM proxies, or
receives browser objects.

The bridge provides:

- continuous RGB565 framebuffer painting through `requestAnimationFrame`;
- pointer, touch, pen, wheel, keyboard, gamepad, and focus input;
- Web Audio playback and capture with explicit permission state;
- one-shot and periodic browser timers with Python callback delivery; and
- Asyncify-backed Fetch used by frozen `requests` and `mip`.

The Python backends are `displaydev.wasmdisplay.WasmDisplay`,
`audiodev.wasm_audio`, and `multimer`'s `wasm` source. Their automatic selectors prefer
these providers only when `_wasm_bridge` imports successfully. The display
owns one RGB565 `bytearray`; the browser scans it each animation frame, so
there is no explicit present or double-buffer protocol.

[`bin/wasm.py`](https://github.com/PyDevices/pydevices/blob/main/bin/wasm.py) (and [`bin/pyscript.py`](https://github.com/PyDevices/pydevices/blob/main/bin/pyscript.py)) require `PyDevices.github.io`,
`gallery`, and `mip` checked out as siblings of this repository —
the host serves gallery content and MIP packages straight out of those
directories.

Run an application through the first-party gallery host with:

```bash
bin/wasm.py -m bouncing_balls
bin/wasm.py my_app.py
bin/wasm.py --no-open -m paint
```

The launcher only stages URL intent, serves those checkouts, prints the URL, and
opens a browser. Playwright is maintained as a separate test harness.

Audio and microphone use require the host page's Enable Audio/Microphone
control. Backends raise a clear permission error until the relevant control
has been used.

### Audio in the browser

A browser blocks sound until the person has used the page. Until then
`play()` raises `RuntimeError("audio output is disabled; use the host Enable
Audio control")`, and the output is left as it was, so you can try again. The
gallery host page unlocks audio on the first click, tap or key press; a page
of your own has to do the same with its Enable Audio control. Try at start,
and retry on the next input event:

```python
import events

def start_sound(out, sample, app):
    def attempt(event=None):
        try:
            out.play(sample, loop=True)
        except RuntimeError:
            return              # still locked; wait for the next input
        for kind in (events.MOUSEBUTTONDOWN, events.KEYDOWN):
            app.off(kind, attempt)

    attempt()
    if not out.playing:
        app.on([events.MOUSEBUTTONDOWN, events.KEYDOWN], attempt)
```

Execution stays on the browser main thread; running the VM in a worker is
not part of this backend contract.
