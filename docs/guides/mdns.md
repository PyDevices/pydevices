# mdns

`mdns` finds things on your local network the way phones and laptops do
(printers, smart speakers, screens you can cast to, other boards) and lets
your program announce what it offers, so they can find it. Ask for a kind of
service and you get each device that offers it, with its name, address and
port.

```python
import mdns

server = mdns.Server(None)          # on a board: network.WLAN(network.STA_IF)
for s in server.find(service_type="_display", protocol="_tcp"):
    print(s.instance_name, s.ipv4_address, s.port)

server.advertise_service(service_type="_http", protocol="_tcp", port=8080)
```

```
Bedroom 65" TV 192.168.1.129 7250
75" TCL Roku TV 192.168.1.140 7250
```

It's CircuitPython's `mdns` module, and the same code runs everywhere:

| Where | Where `mdns` comes from |
|---|---|
| CircuitPython | Built in. |
| MicroPython | Built into firmware from [micropython-pydevices](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/mdns), on esp32, rp2 boards with Wi-Fi, unix and Windows. |
| CPython | `mdns.py` in `pydevices-desktop`, over [python-zeroconf](https://pypi.org/project/zeroconf/), which installs with it. |

On CPython, install `pydevices-desktop` ([install-workflows.md](../get-started/install.md#desktop-with-pip)).
If zeroconf is missing, `import mdns` says how to install it.

## Finding services

`server.find(service_type=..., protocol=..., timeout=1)` returns a tuple of
`RemoteService`, one for each device that answered within `timeout` seconds.
The arguments are keyword-only, as they are in CircuitPython. Some service
types you'll meet:

| Service | What answers |
|---|---|
| `"_display", "_tcp"` | Screens that take a Miracast cast over the network (Rokus, many smart TVs) |
| `"_googlecast", "_tcp"` | Chromecasts and Google TVs |
| `"_airplay", "_tcp"` | AirPlay receivers |
| `"_spotify-connect", "_tcp"` | Spotify Connect speakers, and the Spotify app on a computer |
| `"_ipp", "_tcp"` | Printers |
| `"_http", "_tcp"` | Anything with a web page it announces |

Each `RemoteService` has `instance_name` (the device's own name for the
service), `hostname` (its network name, without `.local`), `ipv4_address`
(or `None` if it gave none), `port`, `service_type` and `protocol`. On
CPython and CircuitPython `ipv4_address` is an `ipaddress.IPv4Address`; on
MicroPython it's a string. `str()` of either is the dotted address.

## Advertising a service

`server.advertise_service(service_type=..., protocol=..., port=..., txt_records=None)`
answers for your service until you `deinit()` the server. `txt_records` is up
to 32 strings, `"key=value"` or a key alone. Call it again for the same
service to change its port or records.

`server.instance_name` is the name your services go by, and
`server.hostname` the name your device answers to as `<hostname>.local`.
Both can be set.

## One server at a time

As in CircuitPython, one `mdns.Server` may be live at a time; a second raises
`RuntimeError`. Keep one for the life of your program, or `deinit()` it when
you're done.

`mdns.Server(None)` uses every network the computer is on. A computer on more
than one network can name the one to use by its address:
`mdns.Server("192.168.1.20")`.

## Changes from pydevices 0.7.4

0.7.4 had a pure-Python `mdns.py` in the `pydevices` package that could find
services but not advertise them. It's gone: on MicroPython, `mdns` now comes
with the firmware, and on CPython from `pydevices-desktop`. Code written for
it needs these changes:

- `find()` takes keywords: `find(service_type="_http", protocol="_tcp")`.
- `mdns.resolve()` is gone. Look a `.local` name up with
  `socket.getaddrinfo("p4-devkit.local", 80)`.
- `RemoteService.txt` is gone, as CircuitPython has no such attribute.
- `Server(None, interface="192.168.1.20")` is now `Server("192.168.1.20")`.
- A second `Server` while one is live raises `RuntimeError`.

## What it doesn't find

It finds only what announces itself on mDNS. A Windows PC with its Wireless
Display app open, for one, may answer only over Wi-Fi Direct.

Under WSL with mirrored networking, a Linux program and a Windows program on
the same computer don't hear each other's announcements, though both find,
and are found by, every other device on the network.
