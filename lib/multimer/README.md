# multimer

One `machine.Timer`-shaped `Timer`, one clock, and one dispatcher, on every
interpreter PyDevices runs on: CPython, MicroPython (boards, unix, windows,
wasm) and CircuitPython.

Canonical source: [pydevices/lib/multimer](https://github.com/PyDevices/pydevices/tree/main/lib/multimer).

## Install

### CPython (TestPyPI)

```bash
pip install \
  -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  pydevices
```

`pydevices` is one distribution covering the whole core `lib/` tree. MIP
ships the same set as one `pydevices` package.

### MicroPython (MIP)

```python
import mip

mip.install("pydevices", index="https://PyDevices.github.io/mip")
```

## Quick start

```python
import multimer
from multimer import Timer

tim = Timer(-1)
tim.init(mode=Timer.PERIODIC, period=500, callback=lambda t: print("tick"))

multimer.sleep_ms(3000)      # or end the script and look at it from >>>
multimer.report()
```

Callbacks run on the main thread at a safe point on every host; the script
can end and the timers keep firing at the prompt. Importing `multimer`
touches nothing until the first timer is armed.

**Everything else — the wake sources per host, `hold()`, `schedule()`,
`keepalive`, `repl()` for hosts with no prompt, and the introspection — is in
[docs/multimer.md](https://github.com/PyDevices/pydevices/blob/main/docs/multimer.md).**

## Links

- [Documentation — multimer](https://github.com/PyDevices/pydevices/blob/main/docs/multimer.md)
- [Source](https://github.com/PyDevices/pydevices/tree/main/lib/multimer)
- [Issues](https://github.com/PyDevices/pydevices/issues)
- Related: `pydevices-pygraphics`, `pydevices-desktop`

## License

MIT — see [LICENSE](https://github.com/PyDevices/pydevices/blob/main/LICENSE).
