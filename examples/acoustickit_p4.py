"""Play the acoustic drum kit out of the ESP32-P4's speaker.

    mpftp put -d COM4 examples/acoustickit_p4.py /acoustickit_p4.py
    mpftp exec -d COM4 'import acoustickit_p4'

Two bars of a plain rock pattern, then a fill, on `audioinstruments`'
`acoustickit` - modal synthesis, no samples, running on `audiomodal.Bank`.

It opens `audio_out` at the board's own format (24 kHz mono 16-bit, which is
what this panel's ES8311 and speaker are) and asks for `latency="low"`, which
is the 10 ms chunk and four-chunk lookahead an instrument responding to events
wants rather than the buffered profile file playback wants.

The pattern is clocked off `ticks_ms`, which is the same clock the pump uses.

That is worth stating because the obvious alternative is wrong. `service()`
does not push a fixed amount per call and does not block: it reads `ticks_ms`
itself, works out how many frames the schedule owes by now, and returns having
done nothing at all if the answer is none. So counting `service()` calls as
though each were a chunk of audio measures how fast the interpreter loops, not
how much sound has been made - and the whole pattern fires in under a second
while the pump quietly produces real time underneath it. Written that way
first, and that is exactly what it did.
"""

from time import ticks_diff, ticks_ms

import board_peripherals
from audiodev import AudioFormat

import audioinstruments

RATE = 24000
BPM = 96
SIXTEENTH_MS = 60000.0 / BPM / 4.0

#: GM notes, the ones a rock pattern needs.
KICK, SNARE, CLOSED, OPEN, CRASH = 36, 38, 42, 46, 49
TOM_HI, TOM_MID, TOM_LO = 48, 47, 41

#: One bar of sixteenths: (step, note, velocity).
BAR = (
    (0, KICK, 112), (0, CLOSED, 78), (0, CRASH, 96),
    (2, CLOSED, 58),
    (4, SNARE, 108), (4, CLOSED, 74),
    (6, CLOSED, 56),
    (8, KICK, 104), (8, CLOSED, 78),
    (10, KICK, 72), (10, CLOSED, 56),
    (12, SNARE, 110), (12, CLOSED, 74),
    (14, CLOSED, 60),
)
BAR_NO_CRASH = tuple(row for row in BAR if row[1] != CRASH)
FILL = (
    (0, KICK, 108), (0, CLOSED, 74),
    (4, SNARE, 96), (6, SNARE, 74),
    (8, TOM_HI, 104), (10, TOM_HI, 82),
    (12, TOM_MID, 108), (13, TOM_MID, 76),
    (14, TOM_LO, 116), (15, TOM_LO, 88),
)
PATTERN = (BAR, BAR_NO_CRASH, BAR_NO_CRASH, FILL)


def main(bars=4):
    out = board_peripherals.audio_out(AudioFormat(RATE, 1, 16), latency="low")
    out.set_volume(100)          # on-device demos play at full volume
    kit = audioinstruments.create("acoustickit", RATE, channel_count=1)
    out.play(kit.output)

    total_steps = bars * 16
    step = 0
    started = ticks_ms()
    while step < total_steps:
        out.service()
        elapsed = ticks_diff(ticks_ms(), started)
        while step < total_steps and elapsed >= step * SIXTEENTH_MS:
            if step % 16 == 0:
                # One line per bar. It is also what keeps `mpftp exec` alive:
                # its per-character quiet timeout is about ten seconds and a
                # bar at this tempo is two and a half, so a silent run of more
                # than four bars would be reported as a dead board.
                print("bar %d" % (step // 16 + 1))
            bar = PATTERN[(step // 16) % len(PATTERN)]
            for at, note, velocity in bar:
                if at == step % 16:
                    kit.note_on(note, velocity)
            step += 1

    # Let the last crash and the toms ring out rather than cutting them.
    ringing = ticks_ms()
    while ticks_diff(ticks_ms(), ringing) < 3000:
        out.service()
    out.stop()
    played = ticks_diff(ticks_ms(), started) / 1000.0
    expected = bars * 16 * SIXTEENTH_MS / 1000.0 + 3.0
    print("acoustickit: %d bars at %d bpm, %d Hz mono" % (bars, BPM, RATE))
    print("  %.1f s played, %.1f s expected" % (played, expected))


if __name__ == "__main__":
    main()
