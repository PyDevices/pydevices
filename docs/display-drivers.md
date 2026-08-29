# Display drivers

MicroPython display controller drivers for use with `displaydev.busdisplay.BusDisplay`.

Source: [`drivers/display/`](https://github.com/PyDevices/pydevices/tree/main/drivers/display)

## Init sequence formats

Three formats are supported:

1. **CircuitPython DisplayIO bytearray** — e.g. [`gc9a01.py`](https://github.com/PyDevices/pydevices/blob/main/drivers/display/gc9a01.py)
2. **List of tuples** — e.g. [`st7789.py`](https://github.com/PyDevices/pydevices/blob/main/drivers/display/st7789.py)
3. **Manual init sequence** — e.g. [`st7796.py`](https://github.com/PyDevices/pydevices/blob/main/drivers/display/st7796.py)

## Constructor API

Drivers follow CircuitPython DisplayIO conventions, including rotation as `0`, `90`, `180`, `270` (not 0–3).

## Installing drivers

Board config packages install the drivers they need. To install individually:

```python
mip.install("github:PyDevices/pydevices/drivers/display/st7789.py", target="./drivers/display")
```

Board installers include the display driver they require directly from this
repository. Individual Python drivers can also be installed from their raw
GitHub file; they are not separate PyDevices MIP-index packages.

## CircuitPython

On CircuitPython, prefer Adafruit's display drivers and the PyDevices `BusDisplay` wrapper. (pydevices-examples' standalone CircuitPython platform guide was retired; its content was folded into the docs of the repos that own it.)
