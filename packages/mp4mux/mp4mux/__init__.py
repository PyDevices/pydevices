# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Write an MP4 file of H.264 video and 16-bit PCM sound while you record.

Hand it each access unit as the encoder makes it, and each block of sound as
the microphone gives it, with the time each was captured; ``close()`` writes
the index that makes the file play::

    import mp4mux

    mp4 = mp4mux.Writer("/sd/clip.mp4", 1280, 720, fps_hint=25)
    mp4.add_video(enc.encode(frame), time.ticks_ms(), enc.keyframe)
    mp4.add_audio(pcm_block, time.ticks_ms())
    mp4.close()

Video is Annex B H.264, as ``h264enc`` and most encoders give it. The start
codes are stripped and each NAL unit is stored behind its length; the SPS and
PPS go into the track's ``avcC`` box. Frames keep the times they were given,
so a frame rate that varies plays back at the speed it was recorded.

Sound is 16-bit little-endian PCM, stored as QuickTime's ``sowt``, which
ffmpeg, VLC and Windows read. A gap in the times given is filled with silence,
so the sound stays in step with the picture when a read comes late.

The sample tables live in RAM until ``close()``: about 12 bytes a frame and 8
a block of sound, preallocated for ``max_seconds`` and grown past it. If
power is lost before ``close()``, the file has its media but no index, and
players refuse it; record in slices of a few minutes to bound what that
costs.
"""

import struct
from array import array

try:
    from micropython import const
except ImportError:  # CPython

    def const(x):
        return x


_VIDEO_TIMESCALE = const(90000)
_MOVIE_TIMESCALE = const(1000)
_GAP_MS = const(40)  # a sound gap longer than this is filled with silence
_NAL_SPS = const(7)
_NAL_PPS = const(8)
_NAL_AUD = const(9)
_LIMIT = 0xFFFFFFFF


class _Table:
    """A growable table of big-endian 32-bit values, written out as is."""

    def __init__(self, capacity):
        self.buf = bytearray(4 * max(capacity, 16))
        self.n = 0

    def append(self, value):
        if 4 * self.n == len(self.buf):
            self.buf.extend(bytearray(len(self.buf)))
        struct.pack_into(">I", self.buf, 4 * self.n, value)
        self.n += 1

    def get(self, i):
        return struct.unpack_from(">I", self.buf, 4 * i)[0]

    def set(self, i, value):
        struct.pack_into(">I", self.buf, 4 * i, value)

    def data(self):
        return memoryview(self.buf)[: 4 * self.n]


def _box(kind, *parts):
    size = 8
    for p in parts:
        size += len(p)
    return [struct.pack(">I4s", size, kind)] + list(parts)


def _join(chunks):
    out = []
    for c in chunks:
        if isinstance(c, list):
            out.extend(c)
        else:
            out.append(c)
    return out


def _size(chunks):
    n = 0
    for c in chunks:
        n += len(c)
    return n


def _container(kind, *children):
    body = _join(children)
    return [struct.pack(">I4s", 8 + _size(body), kind)] + body


def _full(kind, version, flags, *parts):
    return _box(kind, struct.pack(">I", (version << 24) | flags), *parts)


def _rbsp(nal):
    """The NAL unit's payload with emulation-prevention bytes removed."""
    out = bytearray()
    zeros = 0
    for b in nal[1:]:
        if zeros >= 2 and b == 3:
            zeros = 0
            continue
        out.append(b)
        zeros = zeros + 1 if b == 0 else 0
    return out


class _Bits:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def bit(self):
        byte = self.data[self.pos >> 3]
        b = (byte >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return b

    def ue(self):
        zeros = 0
        while self.bit() == 0:
            zeros += 1
        v = 0
        for _ in range(zeros):
            v = (v << 1) | self.bit()
        return (1 << zeros) - 1 + v


def _avcc(sps, pps):
    """The ``avcC`` box body for one SPS and one PPS."""
    profile = sps[1]
    body = bytearray((1, profile, sps[2], sps[3], 0xFF, 0xE1))
    body += struct.pack(">H", len(sps)) + sps
    body += b"\x01" + struct.pack(">H", len(pps)) + pps
    if profile in (100, 110, 122, 144):
        # High profiles carry the chroma format and bit depths too.
        bits = _Bits(_rbsp(sps)[3:])
        bits.ue()  # seq_parameter_set_id
        chroma = bits.ue()
        if chroma == 3:
            bits.bit()  # separate_colour_plane_flag
        luma = bits.ue()
        chroma_depth = bits.ue()
        body += bytes((0xFC | chroma, 0xF8 | luma, 0xF8 | chroma_depth, 0))
    return bytes(body)


def _nals(au):
    """Yield (start, end) of each NAL unit in an Annex B access unit."""
    find = au.find
    n = len(au)
    i = find(b"\x00\x00\x01")
    while i >= 0:
        start = i + 3
        nxt = find(b"\x00\x00\x01", start)
        end = n if nxt < 0 else nxt
        while end > start and au[end - 1] == 0:
            end -= 1  # the leading zero of a four-byte start code
        if end > start:
            yield start, end
        i = nxt


def _runs(table, count):
    """Run-length encode the first ``count`` values of a `_Table` for stts."""
    out = bytearray()
    entries = 0
    if count:
        run_value = table.get(0)
        run = 1
        for i in range(1, count):
            v = table.get(i)
            if v == run_value:
                run += 1
            else:
                out += struct.pack(">II", run, run_value)
                entries += 1
                run_value = v
                run = 1
        out += struct.pack(">II", run, run_value)
        entries += 1
    return entries, out


class Writer:
    """An MP4 file being recorded.

    Args:
        path (str): Where to write it. An existing file is replaced.
        width (int): The video's width in pixels.
        height (int): The video's height in pixels.
        fps_hint (float): The frame rate you expect; it sizes the tables and
            sets the last frame's duration. The file keeps the real times.
        audio_rate (int): The sound's sample rate in Hz.
        audio_channels (int): 1 or 2.
        max_seconds (int): The length the tables are preallocated for.
    """

    def __init__(self, path, width, height, fps_hint=25, audio_rate=16000, audio_channels=1, *, max_seconds=600):
        self.width = width
        self.height = height
        self.fps_hint = fps_hint
        self.audio_rate = audio_rate
        self.audio_channels = audio_channels
        self._frame_bytes = 2 * audio_channels
        frames = int(fps_hint * max_seconds) + 1
        self._v_sizes = _Table(frames)
        self._v_offsets = _Table(frames)
        self._v_durations = _Table(frames)
        self._v_sync = _Table(frames // 8)
        self._v_count = 0
        self._v_t0 = None
        self._v_last = None
        self._sps = None
        self._pps = None
        blocks = max_seconds * 25
        self._a_offsets = _Table(blocks)
        self._a_frames = _Table(blocks)
        self._a_total = 0
        self._a_t0 = None
        self._f = open(path, "wb")
        self._f.write(
            b"".join(_box(b"ftyp", b"isom", struct.pack(">I", 512), b"isomiso2avc1mp41"))
        )
        self._mdat = self._tell()
        self._f.write(struct.pack(">I4s", 0, b"mdat"))
        self._pos = self._mdat + 8
        self.closed = False

    def _tell(self):
        return self._f.seek(0, 1)

    def _check_room(self, more):
        if self._pos + more > _LIMIT:
            raise OSError("an MP4 file here holds up to 4 GB: start a new one")

    # -- video ----------------------------------------------------------------

    def add_video(self, access_unit, pts_ms, keyframe):
        """Add one access unit of Annex B H.264.

        Frames before the first keyframe that carries an SPS and a PPS are
        dropped, since nothing could decode them.

        Args:
            access_unit (bytes): One frame's NAL units, with start codes.
            pts_ms (int): When it was captured, in milliseconds, on the same
                clock as the sound's.
            keyframe (bool): True for an IDR frame.

        Returns:
            bool: True when the frame was written.
        """
        raw = access_unit
        if not isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw)
        keep = []
        for start, end in _nals(raw):
            kind = raw[start] & 0x1F
            if kind == _NAL_SPS:
                if self._sps is None:
                    self._sps = bytes(raw[start:end])
                continue
            if kind == _NAL_PPS:
                if self._pps is None:
                    self._pps = bytes(raw[start:end])
                continue
            if kind == _NAL_AUD:
                continue
            keep.append((start, end))
        if self._v_count == 0 and not (keyframe and self._sps and self._pps):
            return False
        if not keep:
            return False
        size = 0
        for start, end in keep:
            size += 4 + end - start
        self._check_room(size)
        f = self._f
        mv = memoryview(raw)
        for start, end in keep:
            f.write(struct.pack(">I", end - start))
            f.write(mv[start:end])
        if self._v_count:
            self._v_durations.append(max(1, int((pts_ms - self._v_last) * 90)))
        else:
            self._v_t0 = pts_ms
        self._v_last = pts_ms
        self._v_offsets.append(self._pos)
        self._v_sizes.append(size)
        self._v_count += 1
        if keyframe:
            self._v_sync.append(self._v_count)
        self._pos += size
        return True

    # -- sound ----------------------------------------------------------------

    def add_audio(self, pcm, pts_ms):
        """Add a block of 16-bit little-endian PCM, ``audio_channels``
        interleaved.

        Args:
            pcm (bytes): Whole frames of samples: bytes, a bytearray, a
                memoryview of bytes, or an ``array("h")``.
            pts_ms (int): When its first sample was captured, in
                milliseconds, on the same clock as the video's.
        """
        fb = self._frame_bytes
        n = len(pcm)
        if isinstance(pcm, array):
            n *= 2  # 16-bit samples; MicroPython's array has no itemsize
        if n % fb:
            raise ValueError("pcm must be whole frames of %d bytes" % fb)
        if not n:
            return
        silence = 0
        if self._a_t0 is None:
            self._a_t0 = pts_ms
        else:
            due = self._a_t0 + self._a_total * 1000 // self.audio_rate
            if pts_ms - due > _GAP_MS:
                silence = (pts_ms - due) * self.audio_rate // 1000
        self._check_room(silence * fb + n)
        offset = self._pos
        if silence:
            zeros = bytes(fb * min(silence, 1024))
            left = silence
            while left:
                k = min(left, 1024)
                self._f.write(zeros if k == 1024 else zeros[: k * fb])
                left -= k
        self._f.write(pcm)
        frames = silence + n // fb
        self._a_offsets.append(offset)
        self._a_frames.append(frames)
        self._a_total += frames
        self._pos += fb * frames

    def flush(self):
        """Push what has been written so far to the file system."""
        self._f.flush()

    # -- the index ------------------------------------------------------------

    def close(self):
        """Write the index and close the file. A file closed with no video
        and no sound holds no tracks."""
        if self.closed:
            return
        self.closed = True
        f = self._f
        try:
            f.seek(self._mdat)
            f.write(struct.pack(">I", self._pos - self._mdat))
            f.seek(self._pos)
            for chunk in self._moov():
                f.write(chunk)
        finally:
            f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def duration_ms(self):
        """The length of what has been recorded so far."""
        t0, video, audio = self._spans()
        end = 0
        for start, length in (video, audio):
            if length:
                end = max(end, start - t0 + length)
        return end

    def _video_ms(self):
        if not self._v_count:
            return 0
        ticks = 0
        for i in range(self._v_durations.n):
            ticks += self._v_durations.get(i)
        return (ticks + self._last_duration()) // 90

    def _last_duration(self):
        if self._v_durations.n:
            return self._v_durations.get(self._v_durations.n - 1)
        return int(_VIDEO_TIMESCALE / self.fps_hint)

    def _spans(self):
        video = (self._v_t0 or 0, self._video_ms())
        audio = (self._a_t0 or 0, self._a_total * 1000 // self.audio_rate)
        starts = [s for s, n in (video, audio) if n]
        t0 = min(starts) if starts else 0
        return t0, video, audio

    def _moov(self):
        t0, video, audio = self._spans()
        movie_ms = 0
        traks = []
        track_id = 1
        if self._v_count:
            self._v_durations.append(self._last_duration())
            traks.append(self._video_trak(track_id, video[0] - t0, video[1]))
            movie_ms = max(movie_ms, video[0] - t0 + video[1])
            track_id += 1
        if self._a_total:
            traks.append(self._audio_trak(track_id, audio[0] - t0, audio[1]))
            movie_ms = max(movie_ms, audio[0] - t0 + audio[1])
            track_id += 1
        mvhd = _full(
            b"mvhd", 0, 0,
            struct.pack(">IIII", 0, 0, _MOVIE_TIMESCALE, movie_ms),
            struct.pack(">IH", 0x00010000, 0x0100) + bytes(10),
            _MATRIX,
            bytes(24),
            struct.pack(">I", track_id),
        )
        return _container(b"moov", mvhd, *traks)

    def _tkhd(self, track_id, duration_ms, audio):
        return _full(
            b"tkhd", 0, 3,
            struct.pack(">IIIII", 0, 0, track_id, 0, duration_ms),
            bytes(8),
            struct.pack(">HHHH", 0, 0, 0x0100 if audio else 0, 0),
            _MATRIX,
            struct.pack(">II", 0 if audio else self.width << 16, 0 if audio else self.height << 16),
        )

    @staticmethod
    def _edts(offset_ms, duration_ms):
        if offset_ms <= 0:
            return []
        elst = _full(
            b"elst", 0, 0,
            struct.pack(">I", 2),
            struct.pack(">IiI", offset_ms, -1, 0x00010000),
            struct.pack(">IiI", duration_ms, 0, 0x00010000),
        )
        return _container(b"edts", elst)

    @staticmethod
    def _mdhd(timescale, duration):
        return _full(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, timescale, duration, 0x55C4, 0))

    @staticmethod
    def _hdlr(kind, name):
        return _full(b"hdlr", 0, 0, struct.pack(">I4s", 0, kind), bytes(12), name + b"\x00")

    @staticmethod
    def _dinf():
        url = _full(b"url ", 0, 1)
        return _container(b"dinf", _container(b"dref", [struct.pack(">II", 0, 1)], url))

    def _video_trak(self, track_id, offset_ms, duration_ms):
        n = self._v_count
        ticks = 0
        for i in range(n):
            ticks += self._v_durations.get(i)
        avcc = _box(b"avcC", _avcc(self._sps, self._pps))
        avc1 = _box(
            b"avc1",
            bytes(6) + struct.pack(">H", 1),
            bytes(16),
            struct.pack(">HHIIIH", self.width, self.height, 0x00480000, 0x00480000, 0, 1),
            bytes(32),
            struct.pack(">Hh", 0x0018, -1),
            b"".join(avcc),
        )
        entries, runs = _runs(self._v_durations, n)
        stbl = _container(
            b"stbl",
            _full(b"stsd", 0, 0, struct.pack(">I", 1), b"".join(avc1)),
            _full(b"stts", 0, 0, struct.pack(">I", entries), runs),
            _full(b"stss", 0, 0, struct.pack(">I", self._v_sync.n), self._v_sync.data()),
            _full(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 1, 1)),
            _full(b"stsz", 0, 0, struct.pack(">II", 0, n), self._v_sizes.data()),
            _full(b"stco", 0, 0, struct.pack(">I", n), self._v_offsets.data()),
        )
        vmhd = _full(b"vmhd", 0, 1, bytes(8))
        minf = _container(b"minf", vmhd, self._dinf(), stbl)
        mdia = _container(b"mdia", self._mdhd(_VIDEO_TIMESCALE, ticks), self._hdlr(b"vide", b"VideoHandler"), minf)
        return _container(b"trak", self._tkhd(track_id, max(offset_ms, 0) + duration_ms, False), self._edts(offset_ms, duration_ms), mdia)

    def _audio_trak(self, track_id, offset_ms, duration_ms):
        blocks = self._a_offsets.n
        sowt = _box(
            b"sowt",
            bytes(6) + struct.pack(">H", 1),
            bytes(8),
            struct.pack(">HHHH", self.audio_channels, 16, 0, 0),
            struct.pack(">I", self.audio_rate << 16),
        )
        # One stsc entry per run of blocks holding the same number of frames.
        stsc = bytearray()
        entries = 0
        last = None
        for i in range(blocks):
            k = self._a_frames.get(i)
            if k != last:
                stsc += struct.pack(">III", i + 1, k, 1)
                entries += 1
                last = k
        stbl = _container(
            b"stbl",
            _full(b"stsd", 0, 0, struct.pack(">I", 1), b"".join(sowt)),
            _full(b"stts", 0, 0, struct.pack(">III", 1, self._a_total, 1)),
            _full(b"stsc", 0, 0, struct.pack(">I", entries), stsc),
            _full(b"stsz", 0, 0, struct.pack(">II", self._frame_bytes, self._a_total)),
            _full(b"stco", 0, 0, struct.pack(">I", blocks), self._a_offsets.data()),
        )
        smhd = _full(b"smhd", 0, 0, bytes(4))
        minf = _container(b"minf", smhd, self._dinf(), stbl)
        mdia = _container(b"mdia", self._mdhd(self.audio_rate, self._a_total), self._hdlr(b"soun", b"SoundHandler"), minf)
        return _container(b"trak", self._tkhd(track_id, max(offset_ms, 0) + duration_ms, True), self._edts(offset_ms, duration_ms), mdia)


# The identity transform, in 16.16 and 2.30 fixed point.
_MATRIX = struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
