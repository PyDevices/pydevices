"""How healthy is the P4's audio while the drum kit is playing?

    mpftp put -d COM4 examples/acoustickit_p4_probe.py /acoustickit_p4_probe.py
    mpftp exec -d COM4 'import acoustickit_p4_probe as p; p.main()'

Plays the same pattern as `acoustickit_p4.py` and watches three things the ear
would only tell you about once they were already bad:

- **Queue depth.** `I2SPCMOutput.queued_size()` is a byte clock: bytes written
  minus bytes the DMA must have consumed by now. It is also the note-to-sound
  latency, because every queued byte plays before anything pressed now. When it
  reaches zero the stream has underrun and played silence, and the transport
  realigns its clock rather than reporting a negative number - so a run that
  spends time at zero is a run with holes in it, and nothing raises.
- **Pump gap.** The longest wall-clock interval between two `service()` calls.
  The pump can only cover a gap up to its catch-up limit; past that the queue
  drains and the first bullet happens.
- **Headroom.** Wall time spent inside `service()` against wall time elapsed.
  This is the honest "how close to the edge" number, because it includes
  pulling the graph, the mixer, the two banks and the push.
"""

from time import ticks_diff, ticks_ms, ticks_us

import board_peripherals
from audiodev import AudioFormat

import audioinstruments

from acoustickit_p4 import BPM, PATTERN, RATE, SIXTEENTH_MS


def main(bars=4, quiet_bars=1):
    out = board_peripherals.audio_out(AudioFormat(RATE, 1, 16), latency="low")
    out.set_volume(100)
    kit = audioinstruments.create("acoustickit", RATE, channel_count=1)
    out.play(kit.output)
    transport = out.transport
    frame = out.transport.format.frame_size
    rate = float(RATE)

    total_steps = bars * 16
    step = 0
    calls = 0
    at_zero = 0
    depth_min = 1 << 30
    depth_sum = 0
    worst_gap = 0
    busy_us = 0
    started = ticks_ms()
    last_call = started

    # A quiet lead-in first: the queue has to prime before any of this means
    # anything, and a depth read during priming is not a depth read.
    lead = ticks_ms()
    while ticks_diff(ticks_ms(), lead) < quiet_bars * 4 * SIXTEENTH_MS * 4:
        out.service()
    primed = transport.queued_size()

    started = ticks_ms()
    last_call = started
    while step < total_steps:
        now = ticks_ms()
        gap = ticks_diff(now, last_call)
        if gap > worst_gap:
            worst_gap = gap
        last_call = now

        t0 = ticks_us()
        out.service()
        busy_us += ticks_diff(ticks_us(), t0)
        calls += 1

        depth = transport.queued_size()
        depth_sum += depth
        if depth < depth_min:
            depth_min = depth
        if depth == 0:
            at_zero += 1

        elapsed = ticks_diff(ticks_ms(), started)
        while step < total_steps and elapsed >= step * SIXTEENTH_MS:
            if step % 16 == 0:
                print("bar %d" % (step // 16 + 1))
            bar = PATTERN[(step // 16) % len(PATTERN)]
            for at, note, velocity in bar:
                if at == step % 16:
                    kit.note_on(note, velocity)
            step += 1

    wall_ms = ticks_diff(ticks_ms(), started)
    print("")
    print("primed queue      %6.1f ms" % (primed / frame / rate * 1000.0))
    print("queue depth  min  %6.1f ms   mean %6.1f ms"
          % (depth_min / frame / rate * 1000.0,
             (depth_sum / calls) / frame / rate * 1000.0))
    print("reads at zero     %6d of %d  (%.1f%%)"
          % (at_zero, calls, 100.0 * at_zero / calls))
    print("worst pump gap    %6d ms" % worst_gap)
    print("service() busy    %6.1f%% of wall" % (busy_us / 1000.0 / wall_ms * 100.0))
    print("%d bars at %d bpm, %d Hz mono, %.1f s" % (bars, BPM, RATE, wall_ms / 1000.0))
    out.stop()
