"""Play the acoustic drum kit out of the ESP32-P4's speaker.

    mpftp put -d COM4 examples/acoustickit_p4.py /acoustickit_p4.py
    mpftp exec -d COM4 'import acoustickit_p4'

Two bars of a plain rock pattern, then a fill, on `audioinstruments`'
`acoustickit` - modal synthesis, no samples, running on `audiomodal.Bank`.

It opens `audio_out` at the board's own format (24 kHz mono 16-bit, which is
what this panel's ES8311 and speaker are) and asks for `latency="low"`, which
is the 10 ms chunk and four-chunk lookahead an instrument responding to events
wants rather than the buffered profile file playback wants.

The pattern is driven off the pump rather than a clock: `service()` is what
pulls the graph and pushes bytes, so the loop below counts the chunks it has
serviced and strikes on the ones a sixteenth lands on. That keeps the timing
tied to the audio that has actually been produced instead of to `ticks_ms`,
which would drift against it.
"""

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

    # `service()` returns after pushing at most one chunk, so the count of
    # chunks is the clock. chunk_ms is 10 at latency="low".
    chunk_ms = 10.0
    step_chunks = SIXTEENTH_MS / chunk_ms
    total_steps = bars * 16
    step = 0
    chunks = 0.0
    while step < total_steps:
        out.service()
        chunks += 1.0
        while step < total_steps and chunks >= step * step_chunks:
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
    for _ in range(int(3000.0 / chunk_ms)):
        out.service()
    out.stop()
    print("acoustickit: %d bars at %d bpm, %d Hz mono" % (bars, BPM, RATE))


if __name__ == "__main__":
    main()
