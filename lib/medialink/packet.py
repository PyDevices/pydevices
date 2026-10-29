"""The 14-byte header every medialink datagram starts with.

======  =====  ==========================================================
offset  bytes  field
======  =====  ==========================================================
0       2      magic, ``0x4C4D`` ("ML" little-endian)
2       1      version, 1
3       1      kind: ``AUDIO``, ``VIDEO``, ``CONTROL``, ``ACK``, ``PING``
4       1      sub: the codec of a media frame, the op of a control
5       1      flags: ``START`` and ``END`` of a talk spurt
6       1      fragment index
7       1      fragment count
8       2      sequence number
10      4      timestamp, the sender's ms ticks (a control's: its token)
======  =====  ==========================================================

Everything is little-endian. A media frame bigger than one datagram is cut
into fragments that share a sequence number.
"""

import struct

MAGIC = 0x4C4D
VERSION = 1
HEADER = "<HBBBBBBHI"
HEADER_SIZE = 14

# kinds
AUDIO = 1
VIDEO = 2
CONTROL = 3
ACK = 4
PING = 5

# flags
START = 1
END = 2

# control ops
HELLO = 1
BYE = 2
TAKE = 3
RELEASE = 4
EVENT = 5

# ping subs
PING_ASK = 0
PING_ANSWER = 1


def pack_into(buf, kind, sub, flags, frag, frags, seq, stamp):
    struct.pack_into(
        HEADER, buf, 0, MAGIC, VERSION, kind, sub, flags, frag, frags,
        seq & 0xFFFF, stamp & 0xFFFFFFFF,
    )


def pack(kind, sub, flags, frag, frags, seq, stamp, payload=b""):
    buf = bytearray(HEADER_SIZE + len(payload))
    pack_into(buf, kind, sub, flags, frag, frags, seq, stamp)
    buf[HEADER_SIZE:] = payload
    return buf


def unpack(buf, count):
    """``(kind, sub, flags, frag, frags, seq, stamp)``, or None if not ours."""
    if count < HEADER_SIZE:
        return None
    magic, version, kind, sub, flags, frag, frags, seq, stamp = struct.unpack_from(
        HEADER, buf, 0
    )
    if magic != MAGIC or version != VERSION:
        return None
    return kind, sub, flags, frag, frags, seq, stamp
