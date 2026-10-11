# mdns

`mdns` finds things on your local network the way phones and laptops do:
printers, smart speakers, screens you can cast to, other boards. Ask for a
kind of service and you get each device that offers it, with its name,
address and port.

```python
import mdns

server = mdns.Server(None)
for s in server.find("_display", "_tcp"):
    print(s.instance_name, s.ipv4_address, s.port)
```

```
Bedroom 65" TV 192.168.1.129 7250
75" TCL Roku TV 192.168.1.140 7250
```

It has the same shape as CircuitPython's built-in `mdns` module, so the same
code finds services on CircuitPython, MicroPython and a desktop. On
CircuitPython the built-in module is the one `import mdns` gets; this one is
for MicroPython boards with a network, and for CPython. It's part of the
`pydevices` package:

```python
import mip
mip.install("pydevices", index="https://PyDevices.github.io/mip")
```

## Finding services

`Server.find(service_type, protocol, *, timeout=1)` returns a tuple of
`RemoteService`, one for each device that answered within `timeout`
seconds. Some service types you'll meet:

| Service | What answers |
|---|---|
| `"_display", "_tcp"` | Screens that take a Miracast cast over the network (Rokus, many smart TVs) |
| `"_googlecast", "_tcp"` | Chromecasts and Google TVs |
| `"_airplay", "_tcp"` | AirPlay receivers |
| `"_spotify-connect", "_tcp"` | Spotify Connect speakers |
| `"_ipp", "_tcp"` | Printers |
| `"_http", "_tcp"` | Anything with a web page it announces |

Each `RemoteService` has:

| Attribute | |
|---|---|
| `instance_name` | The device's own name for the service (Bedroom 65" TV) |
| `hostname` | The device's network name, without `.local` |
| `ipv4_address` | Its address, or `None` if it gave none |
| `port` | The service's port |
| `service_type`, `protocol` | What you asked for |
| `txt` | The service's TXT record as a dict (not in CircuitPython's module) |

`ipv4_address` is a string here and an `ipaddress.IPv4Address` on
CircuitPython; `str()` of either is the dotted address.

On a board, pass the network interface (`network.WLAN(network.STA_IF)`) or
`None`; the answer is the same. A computer on more than one network can
pick the one to ask on with `mdns.Server(None, interface="192.168.1.20")`.

## Names

`mdns.resolve("p4-devkit")` returns the address of `p4-devkit.local`, or
`None` if nothing answers. CircuitPython's module leaves this to
`socketpool.getaddrinfo()`; here it's one call.

`server.hostname` is this device's own name on the network; setting it on a
board renames the board.

## What it doesn't do

It doesn't announce services: `advertise_service()` raises
`NotImplementedError`. Answering other devices' questions takes a
responder, which on a board is the firmware's own (the one that makes
`<hostname>.local` work).

It finds only what announces itself on mDNS. A Windows PC with its Wireless
Display app open, for one, announces itself only over Wi-Fi Direct, so it
doesn't answer `"_display", "_tcp"` even though you can cast to it.

## How it asks

`find()` sends one multicast question, sends it again halfway through the
timeout (multicast gets lost on Wi-Fi), and asks a second time for anything
the first answers left out, such as a port or an address. It asks from an
ordinary spare port rather than mDNS's own, 5353, because a board's firmware
already holds that one. Responders answer such a question straight back to
the asker ([RFC 6762, section 6.7](https://www.rfc-editor.org/rfc/rfc6762#section-6.7)).
