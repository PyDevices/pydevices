"""Audio codecs, and choosing one to fit a link.

A codec turns a frame of signed 16-bit little-endian PCM into a payload and
back. Each payload stands alone, so a lost datagram costs its own frame and
nothing after it.

* :data:`PCM16`, id 0: the samples as they are. 16 kHz mono is 256 kbit/s,
  which Wi-Fi carries easily.
* :data:`ADPCM`, id 1: IMA ADPCM, four bits a sample, a quarter of the size.
  16 kHz mono is 64 kbit/s, which fits links like BLE. Mono only.

:func:`choose` picks the plainer one whenever the link has room for it.
"""

import struct


class PCM16:
    id = 0
    name = "pcm16"
    bits = 16

    @staticmethod
    def encode(pcm, channels=1):
        return bytes(pcm)

    @staticmethod
    def decode(payload, channels=1):
        return payload


_STEPS = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41,
    45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209,
    230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876,
    963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749,
    3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630,
    9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767,
)
_INDEX = (-1, -1, -1, -1, 2, 4, 6, 8)


def _step(code, predictor, index):
    step = _STEPS[index]
    diff = step >> 3
    if code & 4:
        diff += step
    if code & 2:
        diff += step >> 1
    if code & 1:
        diff += step >> 2
    if code & 8:
        predictor -= diff
        if predictor < -32768:
            predictor = -32768
    else:
        predictor += diff
        if predictor > 32767:
            predictor = 32767
    index += _INDEX[code & 7]
    if index < 0:
        index = 0
    elif index > 88:
        index = 88
    return predictor, index


class ADPCM:
    """IMA ADPCM. The payload is the starting predictor, the step index, a
    spare byte, then two samples a byte, low nibble first. A frame holds an
    even number of samples.

    The encoder carries its step size from one frame to the next, so a
    stream doesn't start over at every frame; the header carries it too, so
    the decoder needs nothing from the frame before. Use one encoder a
    stream.
    """

    id = 1
    name = "adpcm"
    bits = 4

    def __init__(self):
        self._predictor = None
        self._index = 0

    def encode(self, pcm, channels=1):
        if channels != 1:
            raise ValueError("ADPCM here is mono only")
        count = len(pcm) // 2
        if count % 2:
            raise ValueError("ADPCM frames hold an even number of samples")
        samples = struct.unpack("<%dh" % count, pcm)
        out = bytearray(4 + count // 2)
        predictor = self._predictor
        if predictor is None:
            predictor = samples[0] if count else 0
        index = self._index
        struct.pack_into("<hBB", out, 0, predictor, index, 0)
        at = 4
        high = False
        for sample in samples:
            diff = sample - predictor
            code = 0
            if diff < 0:
                code = 8
                diff = -diff
            step = _STEPS[index]
            if diff >= step:
                code |= 4
                diff -= step
            step >>= 1
            if diff >= step:
                code |= 2
                diff -= step
            step >>= 1
            if diff >= step:
                code |= 1
            predictor, index = _step(code, predictor, index)
            if high:
                out[at] |= code << 4
                at += 1
            else:
                out[at] = code
            high = not high
        self._predictor = predictor
        self._index = index
        return bytes(out)

    @staticmethod
    def decode(payload, channels=1):
        predictor, index, _spare = struct.unpack_from("<hBB", payload, 0)
        codes = len(payload) - 4
        out = bytearray(4 * codes)
        at = 0
        for byte in memoryview(payload)[4:]:
            for code in (byte & 15, byte >> 4):
                predictor, index = _step(code, predictor, index)
                struct.pack_into("<h", out, at, predictor)
                at += 2
        return bytes(out)


PCM16 = PCM16()
ADPCM = ADPCM()
CODECS = {PCM16.id: PCM16, ADPCM.id: ADPCM}


def by_id(codec_id):
    try:
        return CODECS[codec_id]
    except KeyError:
        raise ValueError("unknown codec %d" % codec_id) from None


def choose(bandwidth, rate, channels=1):
    """The codec for a link of ``bandwidth`` bits a second.

    Plain PCM when the link carries it with half again to spare, ADPCM when
    it doesn't. Raises ValueError when not even ADPCM fits.
    """
    if bandwidth >= rate * channels * 16 * 3 // 2:
        return PCM16
    if channels == 1 and bandwidth >= rate * 4 * 5 // 4:
        return ADPCM
    raise ValueError("a %d bit/s link can't carry %d Hz audio" % (bandwidth, rate))
