"""Audio and video between boards, and between boards and computers.

medialink sends live media from one device to another over the local
network: a walkie-talkie, an intercom, a baby monitor. It runs on
MicroPython, CircuitPython and CPython, so a board and a computer are peers
of the same kind.

It is three layers, so a new kind of link stays small:

* **media** (:mod:`medialink.intercom`, :mod:`medialink.codec`): frames and
  their timestamps, the half-duplex floor, the codec that fits the link;
* **transport** (:mod:`medialink.transport`): open, send, receive, close,
  and the link's MTU and bandwidth. UDP over IP is the one built;
* **discovery** (:mod:`medialink.discovery`): finds a peer by name and
  hands back its address. mDNS is the one built.

:class:`Link` ties a transport to one peer::

    import medialink

    link = medialink.Link(medialink.UDPTransport(47800))
    link.connect(("192.168.1.20", 47800))       # PeerUnreachable if absent
    intercom = medialink.Intercom(link, mic, speaker)
    intercom.press()                            # talk...
    intercom.release()                          # ...and listen
"""

from medialink._compat import sleep_ms, ticks_add, ticks_diff, ticks_ms
from medialink.codec import ADPCM, PCM16, choose
from medialink.discovery import MDNS
from medialink.intercom import Intercom
from medialink.link import IDLE, LISTENING, TALKING, FLOOR_NAMES, Frame, Link, PeerUnreachable
from medialink.transport import Transport, UDPTransport

__version__ = "0.1.0"

__all__ = [
    "ADPCM",
    "FLOOR_NAMES",
    "Frame",
    "IDLE",
    "Intercom",
    "LISTENING",
    "Link",
    "MDNS",
    "PCM16",
    "PeerUnreachable",
    "TALKING",
    "Transport",
    "UDPTransport",
    "choose",
    "sleep_ms",
    "ticks_add",
    "ticks_diff",
    "ticks_ms",
]
