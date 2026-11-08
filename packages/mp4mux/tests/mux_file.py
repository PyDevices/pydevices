# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Mux an Annex B H.264 file and a raw PCM file into an MP4, on any Python.

    micropython packages/mp4mux/tests/mux_file.py in.h264 in.pcm out.mp4

The video stream must carry access unit delimiters (x264's ``aud=1``), which
is where it is split into frames. Frame times vary between 30 and 50 ms, and
the sound starts 100 ms after the picture with a 200 ms hole in it, so the
file exercises variable frame rate, the edit list and the silence fill.
"""

import sys

try:
    sys.path.insert(0, __file__.rsplit("/", 2)[0])
except (NameError, IndexError):
    pass

import mp4mux  # noqa: E402

FRAME_MS = (30, 40, 50)
AUDIO_BLOCK = 320  # frames, 20 ms at 16 kHz
AUDIO_START_MS = 100
HOLE_AT_MS = 1000
HOLE_MS = 200


def access_units(data):
    """Split an Annex B stream at its access unit delimiters."""
    marks = []
    i = data.find(b"\x00\x00\x01\x09")
    while i >= 0:
        marks.append(i)
        i = data.find(b"\x00\x00\x01\x09", i + 4)
    marks.append(len(data))
    for a, b in zip(marks, marks[1:]):
        yield data[a:b]


def is_keyframe(au):
    i = au.find(b"\x00\x00\x01")
    while i >= 0:
        if au[i + 3] & 0x1F == 5:
            return True
        i = au.find(b"\x00\x00\x01", i + 3)
    return False


def main(video_path, pcm_path, out_path, width=320, height=240):
    with open(video_path, "rb") as f:
        video = f.read()
    with open(pcm_path, "rb") as f:
        pcm = f.read()
    mp4 = mp4mux.Writer(out_path, width, height, 25, audio_rate=16000, audio_channels=1)
    t = 0
    frames = 0
    for au in access_units(video):
        mp4.add_video(au, t, is_keyframe(au))
        t += FRAME_MS[frames % 3]
        frames += 1
    video_end = t
    block = 2 * AUDIO_BLOCK
    t = AUDIO_START_MS
    pos = 0
    while pos + block <= len(pcm) and t < video_end:
        if HOLE_AT_MS <= t < HOLE_AT_MS + HOLE_MS:
            t += 20
            pos += block
            continue
        mp4.add_audio(pcm[pos : pos + block], t)
        t += 20
        pos += block
    mp4.close()
    print("muxed", frames, "frames,", video_end, "ms of video")


if __name__ == "__main__":
    main(*sys.argv[1:4])
