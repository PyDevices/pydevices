"""The audio pump, used without being asked.

``audiopump`` is a C module that pulls a CircuitPython audiosample graph on a
thread the interpreter is not on -- a pthread on unix, a pinned FreeRTOS task
on esp32 -- and writes every block straight into I2S. When the firmware
carries it, everything in :mod:`audiodev` that plays a sample graph goes
through it; when it does not, nothing here does anything and the old path is
untouched. No app asks for a backend.

There is exactly **one** pump: one C task, one I2S channel. So there is one
:class:`Pump` here too, reached through :func:`owner`, and it is what
arbitrates between an :class:`~audiodev.sample_out.AudioOut` graph and a
:class:`~audiodev.PCMOutput` stream that both want to sound. Two clients get
a root ``audiomixer.Mixer`` built for them and the pump is retargeted onto
it; one client is pulled with nothing in the way, which is why a single
player's PCM is byte-identical to the old path's.

Three drivers, because the ports differ in where the bytes land and in
whether there is a thread to land them from:

``RingDriver``
    The desktop (unix, and anything else whose driver has no ``i2s_start``).
    The pump
    fills a RAM ring; :meth:`Pump.next_block` drains it on the interpreter
    thread and hands the bytes to the existing push transport. The DSP leaves
    the interpreter thread; the byte-shovelling stays. Nothing on a desktop
    paces the pump, so this driver parks it between ticks -- see
    :meth:`RingDriver.produce`.

``ServiceDriver``
    WebAssembly, which has no threads. ``audiopump.service()`` runs the same
    C loop on the interpreter thread, filling the same ring, and the audio is
    byte-identical to the unix build's. What changes is that the ring is
    look-ahead rather than slack: a tick of T milliseconds needs a ring
    longer than T.

``BusioDriver``
    esp32. The graph goes to ``audiobusio.I2SOut`` -- CircuitPython's own
    class, with this same pump under it -- built from the board's
    :class:`~audiodev.I2SWire`. **There is one way this firmware plays a
    sample**, and that is it: the output owns the channel, converts anything
    that is not signed 16-bit on the pump's thread, retunes the bus to the
    sample's rate and sizes the DMA descriptor in time. ``audiodev`` writes no
    PCM, opens no peripheral, and is left holding the policy -- the codec, two
    clients, a file, the fault sentence.

A fault in the pump is a sentence, not a traceback and not a dead speaker:
:meth:`Pump.died` turns the status block's error and fault words into one,
and the caller that notices is :class:`AudioOut`, which falls back to the old
pull-on-the-interpreter path for the rest of the process.
"""

# audiopump's Python-facing names that this module needs. A module called
# "audiopump" that lacks them is not the pump -- MicroPython's unix port puts
# the working directory on sys.path, so `import audiopump` in the workspace
# root finds the *checkout directory* as a namespace package and succeeds.
# Importability is not the test; `spawn` is.
_REQUIRED = ("spawn", "shutdown", "running", "retarget", "drain", "park")

_BLOCKS_FOREVER = 0x7FFFFFFF

# audiocore.get_buffer()'s result codes, repeated here so this module does not
# have to import sample_out (which imports it the other way round).
GET_BUFFER_DONE = 0
GET_BUFFER_MORE_DATA = 1

# What the pump publishes when it stops on its own. Word 5 is its own reason
# for leaving the loop; word 24 is the code audioif's funnel left behind.
_ERRORS = {
    1: "a node in the graph returned no buffer",
    2: "a node in the graph returned a null buffer",
    3: "the source ran out",
    4: "the graph's memory was re-used under it",
    5: "a node in the graph faulted",
}
_FAULTS = {
    1: "something in the chain is not an audio node",
    2: "something in the chain was released while it was playing",
    3: "a file-backed source cannot be pulled by the pump",
    4: "a read that would have raised inside the pull",
}

# Sources that read through the VFS or a stream inside get_buffer(). The pump
# refuses them by type name in C (spawn() raises); the same names are here so
# a caller can ask *before* it builds anything, and so AudioOut knows to put a
# Prefetch in front instead of giving up.
FILE_BACKED = ("WaveFile", "MP3Decoder")

_audiopump = None
_looked = False
_driver = None
_driver_looked = False
_busio = None
_busio_looked = False


def module():
    """The ``audiopump`` C module, or None. Imported once, checked properly."""
    global _audiopump, _looked
    if _looked:
        return _audiopump
    _looked = True
    try:
        import audiopump as mod
    except ImportError:
        return None
    for name in _REQUIRED:
        if not hasattr(mod, name):
            return None
    _audiopump = mod
    return mod


def driver():
    """The ``_audioif`` C module -- the pump's platform driver -- or None.

    The pump is two halves. ``audiopump`` is the portable engine and ships
    with audioif on every port; ``_audioif`` is the hardware, and it exists
    only where there is hardware to drive. The I2S channel, the microphone
    ``Input`` and the round-trip probe are ITS names, not the engine's.

    Private by convention, the way ``usbif`` ships a C ``_usbif`` under a
    Python package: ``audiodev`` is the public face, and nothing outside this
    module should import it.
    """
    global _driver, _driver_looked
    if _driver_looked:
        return _driver
    _driver_looked = True
    try:
        import _audioif as mod
    except ImportError:
        return None
    _driver = mod
    return mod


def busio():
    """The ``audiobusio`` C module -- ``I2SOut`` -- or None.

    The *public* face of the audio hardware layer, and CircuitPython's own
    spelling: ``audiobusio.I2SOut(bit_clock, word_select, data).play(sample)``
    runs CircuitPython's own docstring example on this firmware unchanged.
    Everything :mod:`audiodev` does on a board goes through it, so there is
    one way the firmware plays a sample and ``audiodev`` is the policy layer
    over it -- format negotiation, volume, the codec session, two clients,
    files.

    It is checked for ``I2SOut``, not merely imported, for the same reason
    :func:`module` is checked for ``spawn``.
    """
    global _busio, _busio_looked
    if _busio_looked:
        return _busio
    _busio_looked = True
    try:
        import audiobusio as mod
    except ImportError:
        return None
    if not hasattr(mod, "I2SOut"):
        return None
    _busio = mod
    return mod


def driver_name():
    """Which platform driver the engine bound: esp32, pthread, win32, none.

    "none" on a build with no driver linked -- WebAssembly, and anything that
    shipped the engine without the hardware half. That build still pumps;
    ``threaded()`` is False and ``audiopump.service()`` drives the loop.
    """
    mod = module()
    if mod is None or not hasattr(mod, "driver"):
        return "none"
    return mod.driver()


def available():
    """True when this firmware carries a usable pump."""
    return module() is not None


def on_board():
    """True when the pump owns an I2S peripheral (esp32), rather than a ring.

    Asked of the DRIVER, not the engine: the engine is the same code on every
    port and has no idea whether there is an I2S peripheral behind it.
    """
    mod = driver()
    return mod is not None and hasattr(mod, "i2s_start")


def threaded():
    """True where spawn() puts the pull loop on a thread of its own.

    False on WebAssembly, where there is no thread to put it on and
    ``audiopump.service()`` runs the same loop on this one. A build too old to
    answer has a thread, because every build that had the pump before this
    question existed did.
    """
    mod = module()
    if mod is None or not hasattr(mod, "threaded"):
        return True
    return bool(mod.threaded())


def backpressure():
    """True where a full output ring makes the pump wait instead of dropping.

    The one question a desktop driver has to ask before it decides whether to
    park the pump between ticks. With back-pressure the ring *is* the pace --
    exactly as an I2S write is the pace on a board -- so parking is pure cost
    and the pump is left to run. Without it a free-running pump fills the ring
    in milliseconds and loses whole blocks, which is not a glitch you can hear
    past on a recording; it is a hole in the bytes.

    A build too old to answer does **not** have it: every build that had the
    pump before this question existed dropped.
    """
    mod = module()
    if mod is None or not hasattr(mod, "backpressure"):
        return False
    return bool(mod.backpressure())


def now():
    """Frames the pump has pulled since it started, or 0 without one.

    The number an event's frame is compared against, so it is the one to
    schedule from. It is not what a listener has *heard*: subtract whatever
    the sink is holding for that. It wraps every 2^32 frames -- 24.9 hours at
    48 kHz -- and the comparisons inside the queue are wrap-aware, so nothing
    out here has to be.
    """
    mod = module()
    return mod.now() if mod is not None and hasattr(mod, "now") else 0


def events(capacity=96):
    """The pump's event queue, or None on a build with no pump.

    ``audiodev.pump.events()`` is how an app reaches the clock; see
    :meth:`Pump.events` for why the queue belongs to the pump and not to the
    app that asked for it.
    """
    return owner().events(capacity)


def ring_bytes(frame_size, chunk_bytes=0, max_block=0):
    """How deep the desktop output ring is, for *frame_size*-byte frames.

    One rule in one place, because three things have to agree on it: the ring
    :class:`RingDriver` allocates, how far ahead of the interpreter a
    free-running pump therefore gets, and how deep anything **feeding** that
    pump has to be -- a :class:`Prefetch`, above all, which the pump would
    otherwise empty between two ticks.

    **This number is the latency of a live event**, and that is why it is two
    drain windows and not eight. A pump the ring paces keeps the ring full, so
    a note pressed now is heard after everything already in it has been handed
    out. Eight chunks is 160 ms at a 20 ms tick, which is a delay you can play
    against a metronome and hear. Two chunks plus a block is 26 ms at a 10 ms
    tick, which is what the parked pump used to give -- the same latency, with
    the pump off the interpreter's timeline instead of on it.

    The floor is two blocks of the graph, because a graph's block is whatever
    its tail offers -- an ``audiocore.RawSample`` offers its entire buffer, so
    a half-second tone is a 96 kB block -- and a ring that cannot hold one is
    the one case back-pressure cannot rescue: it drops, and counts it.
    """
    return max(2 * int(chunk_bytes or 0) + int(max_block or 0),
               2 * int(max_block or 0), 64 * int(frame_size))


def block_size(sample):
    """Bytes in one pull of *sample*, or 0 if it cannot be asked.

    The audiosample protocol publishes ``sample_rate``, ``channel_count`` and
    ``bits_per_sample`` to Python and **not** ``max_buffer_length``, so the one
    number a ring has to be sized against is the one Python cannot see. The
    pump's ``info()`` reads it off the C base struct. Without it a ring is
    sized by guesswork, and an ``audiocore.RawSample`` hands back its whole
    buffer in a single pull -- a half-second tone is a 96 kB block, which a
    64 kB ring silently drops in its entirety.
    """
    mod = module()
    if mod is None or not hasattr(mod, "info"):
        return 0
    try:
        return int(mod.info(sample)[3])
    except Exception:    # noqa: BLE001 - not an audiosample; the caller copes
        return 0


#: How deep we are inside a method that REARRANGES who is sounding, and how
#: many ticks were turned away because of it. A list rather than two globals
#: so the check on the hot path costs no ``global`` statement.
_BUSY = [0, 0]


def rearranging():
    """True while something is rearranging the pump. A tick must not pull.

    **A service tick arrives between bytecodes.** On a board it rides the
    app's shared timer and is delivered by ``micropython.schedule``, so it
    lands wherever it lands -- including halfway through the method that is
    taking one client off the pump and putting another on. The P4 found the
    first instance of this the hard way: a tick inside
    :meth:`~audiodev.sample_out.AudioOut.stop` saw a player that read exactly
    like a healthy old-path player, pulled a block, wrote it, and opened
    ``machine.I2S`` on the port the pump had just let go of. Both halves of
    that race were seen on silicon.

    `AudioOut._pumping` closed it for **one player's own** methods. It cannot
    close the rest, because the thing being rearranged is *global*: one pump,
    one graph, one peripheral. A tick that services player B while player A
    is inside :meth:`Pump._retarget` reaches the same C module through a
    different Python object, and ``spawn()`` answers the second one with "a
    pump is already spawned".

    So this is the flag, and it is the pump's rather than any player's. It
    nests, because `AudioOut.play` -> `Pump.play` -> `Pump._retarget` is
    three of these deep on one call.
    """
    return _BUSY[0] > 0


def reentered():
    """Ticks turned away because something was rearranging the pump.

    Never a hole: the tick's whole job is to top a buffer up, the buffer is
    hundreds of milliseconds deep, and the next tick does what this one did
    not. A number that climbs says the app's timer is faster than its own
    rearrangement, which is worth knowing and is not worth an exception.
    """
    return _BUSY[1]


def _enter():
    _BUSY[0] += 1


def _leave():
    _BUSY[0] -= 1
    if _BUSY[0] < 0:            # a teardown that unwound past the top
        _BUSY[0] = 0


def _turned_away():
    _BUSY[1] += 1


def retarget(mod, sample, loop=False):
    """Swap a live pump's tail, carrying the OUTPUT's loop flag with it.

    The flag belongs to the tail, not to the pump's whole lifetime. A root
    ``audiomixer.Mixer`` replaced by the one client still sounding is a tail
    whose loop is *that client's*, and for as long as ``retarget()`` took one
    argument it kept whatever ``spawn()`` was called with -- so a looping
    client left alone on a **live** pump stopped at the end of its first lap,
    silently, exactly as a mixed one did before ``_tail()`` learned ``loop=``.

    An engine too old for the keyword still swaps the graph; it just cannot
    carry the flag, which is the bug, so say nothing and let the caller's own
    gate report it rather than losing the audio.
    """
    try:
        mod.retarget(sample, loop=loop)
    except TypeError:
        mod.retarget(sample)


def pumpable(sample):
    """True when the pump can pull *sample* itself.

    A file-backed source cannot: its ``get_buffer`` re-enters the interpreter
    to read the VFS, and the pump thread has no interpreter on it. Those go
    through a :class:`Prefetch` into a ring instead.

    This catches the source at the *tail* only. A ``WaveFile`` buried deep in
    a graph is caught by the pump at the first block instead, as a fault --
    the audiosample protocol gives no way to walk backwards. That is a known
    hole, not an oversight.
    """
    return type(sample).__name__ not in FILE_BACKED


class Prefetch:
    """A file-backed sample, pulled on the interpreter thread into a ring.

    ``WaveFile``, ``MP3Decoder`` and anything else that reads through the VFS
    re-enter the interpreter inside ``get_buffer``, so the pump refuses them.
    They become *producers*: this pulls with ``audiocore`` exactly as the old
    path did, on the thread that is allowed to, and writes what it yields into
    an ``audiopump.Ring`` the pump treats as an ordinary source node.

    It lives here, next to the thing that owns the pump, because the alternative
    is every caller inventing it again. Call :meth:`service` from the same tick
    that services the player.
    """

    def __init__(self, sample, *, frames=256, capacity=6, loop=False,
                 min_bytes=0):
        mod = module()
        if mod is None or not hasattr(mod, "Ring"):
            raise RuntimeError("this firmware has no audiopump.Ring")
        import audiocore

        self._audiocore = audiocore
        self.sample = sample
        self.loop = bool(loop)
        self.done = False
        # Bytes of the file that have gone into the ring. The player needs it:
        # a starved ring emits a whole block of SILENCE and keeps the real
        # frames, so "how many bytes has the pump been given" is the only
        # honest end-of-file, and underruns are counted rather than guessed at.
        self.wrote = 0
        self._held = None          # bytes pulled but not yet accepted
        self._at = 0
        self._feeding = False      # see service(): a tick lands inside it
        # The ring has to outlast one of the player's drain windows. Nothing
        # tops it up while the interpreter is inside produce(), so a ring
        # shallower than that window is emptied by the pump every tick and
        # the underrun rule quietly pastes a block of silence into the file.
        frame = sample.channel_count * sample.bits_per_sample // 8
        block = int(frames) * frame
        self.block = block
        self._tail = None
        if min_bytes:
            need = (int(min_bytes) + block - 1) // block
            capacity = max(int(capacity), 2 * need)
        self.ring = mod.Ring(
            sample_rate=sample.sample_rate,
            channel_count=sample.channel_count,
            frames=frames,
            capacity=int(capacity),
        )
        audiocore.reset_buffer(sample)

    def service(self, limit=None):
        """Top the ring up. Returns bytes written this call.

        **Not re-entrant, and a tick can land inside it.** The block pulled
        from the file lives in ``self._held`` until the ring has taken all of
        it; a second call arriving in the middle pulls the NEXT block over the
        top of it and the frames in between are gone -- a gap in the file that
        nothing counts, because ``wrote`` is only told about what reached the
        ring. A tick that finds this busy does nothing and the next one tops
        the ring up instead; the ring is deeper than a tick by construction.
        """
        if self._feeding:
            return 0
        self._feeding = True
        try:
            return self._service(limit)
        finally:
            self._feeding = False

    def _service(self, limit=None):
        wrote = 0
        while True:
            if self._held is None:
                if self.done:
                    return wrote + self._flush_tail()
                result, buf = self._audiocore.get_buffer(self.sample)
                if buf:
                    self._held = buf
                    self._at = 0
                if result != GET_BUFFER_MORE_DATA:
                    if self.loop and result == GET_BUFFER_DONE:
                        self._audiocore.reset_buffer(self.sample)
                    else:
                        self.done = True
                if not buf:
                    if self.done:
                        return wrote
                    continue
            view = memoryview(self._held)[self._at :]
            took = self.ring.write(view)
            self._at += took
            wrote += took
            self.wrote += took
            if self._at >= len(self._held):
                self._held = None
                self._at = 0
            if took == 0:
                return wrote       # the ring is full; come back next tick
            if limit is not None and wrote >= limit:
                return wrote

    def _flush_tail(self):
        """Pad the last partial block so the file's final frames come out.

        The ring hands the pump whole blocks and holds anything shorter -- an
        underrun is a block of silence and the real frames stay put. At the end
        of a file that is a trap: a WAV whose length is not a whole number of
        blocks leaves its last frames in the ring for ever and the player gets
        silence in their place. A 1.0 s file lost its final 512 bytes that way
        and a 0.4 s one did not, which is exactly the shape of bug that ships.
        """
        level = self.ring.level()
        short = level % self.block
        if not level or not short:
            return 0
        if self._tail is None or len(self._tail) < self.block - short:
            self._tail = bytearray(self.block - short)
        return self.ring.write(memoryview(self._tail)[: self.block - short])

    def fed(self):
        """True when every byte of the file is in the ring.

        Not the same as :attr:`done`, which only says the file has been read
        to the end: a block the ring had no room for is still held here, and
        ``wrote`` has not counted it yet. Treating the two as one ended the
        WAV 22 kB early, which is a clean fade-out and looks like nothing.
        """
        return self.done and self._held is None

    def finished(self):
        """True when the file has been read out *and* the ring has drained."""
        return self.fed() and self.ring.level() == 0

    def deinit(self):
        ring = self.ring
        self.ring = None
        if ring is not None:
            ring.deinit()


class _Driver:
    """Where the pump's blocks go. Subclassed per port.

    Four verbs, because :class:`Pump` rearranges a live output and each port
    answers differently: :meth:`spawn` starts one, :meth:`retarget` swaps the
    tail *without a gap*, :meth:`halt` gives the pump back and :meth:`close`
    gives the peripheral back. The desktop drivers below drive the engine
    directly; the board's drives :class:`~audiobusio.I2SOut`, which owns the
    engine on its side of the line.
    """

    needs_service = True

    def spawn(self, sample, status, loop=False):
        raise NotImplementedError

    def retarget(self, sample, loop=False):
        """Point a running pump at *sample*. No gap, no re-open."""
        retarget(module(), sample, loop)

    def halt(self):
        """Stop the pump. The peripheral, if any, stays open."""
        module().shutdown()

    def status(self):
        """The status block the loop writes, or None to use the caller's."""
        return None

    def produce(self, into):
        """Fill *into* with what the pump has made. Returns bytes."""
        return 0

    def opened(self):
        return True

    def close(self):
        pass


class RingDriver(_Driver):
    """Desktop: the pump fills a RAM ring, the interpreter drains it.

    **The ring is the pace.** There is no DMA on a desktop to block the pump,
    so the ring does it: when it has no room for another block the pump thread
    *sleeps*, and this driver's next drain wakes it. Nothing is dropped,
    ``STATUS_RING_OVF`` is 0 by construction, and the pump runs freely between
    ticks -- which is where the DSP finally leaves the app's timeline.

    It did not always. Until back-pressure landed the C ring dropped whole
    blocks rather than overwriting what had not been taken, so this driver had
    to unpark the pump only *inside* produce() and park it again before
    returning. That kept the bytes exact and cost the whole point of a thread:
    a parked pump is a pump the interpreter waits for, and 96 % of the pump
    path's time was inside produce(), waiting. Letting it free-run instead was
    tried, with a policy that stopped the moment the ring reported a drop --
    an app doing 3.5 ms of its own work per tick went from 1811 ms to 1028 ms,
    **1.8x** -- and the audio lost 71 to 5657 blocks every time. That policy
    cannot work: by the time the counter says a block was dropped, the block is
    gone. Making the ring *wait* is the same win with no byte at risk.

    The park path is still here, and it is not dead code: it is what a build
    whose driver has no wait hook gets, and :func:`backpressure` is the
    question that chooses between them. **Latency is the ring**: with
    back-pressure the pump keeps it full, so what is between a live event and
    the speaker is the ring's own depth plus whatever the host transport holds.
    :meth:`ahead_ms` says what this one's is.
    """

    def __init__(self, frame_size, *, chunk_bytes=0, max_block=0):
        # The floor is one block of the graph, and a graph's block is whatever
        # its tail offers: an audiocore.RawSample hands back its ENTIRE buffer
        # in one call, so a half-second tone is a 96 kB "block". A ring shorter
        # than that can never hold one -- and a ring that can never hold one
        # cannot be waited on, so the C side drops it and counts it, which is
        # the one case where STATUS_RING_OVF still moves. Four blocks, or four
        # drains, whichever is larger.
        self._ring = bytearray(ring_bytes(frame_size, chunk_bytes, max_block))
        self._frame_size = int(frame_size) or 1
        self._parked = False
        self._status = None
        # Decided once, at spawn: the pump either paces itself or has to be
        # parked, and it cannot change under a running graph.
        self._paced_by_ring = False

    def ahead_ms(self, rate=48000):
        """How much audio the ring holds when full, in milliseconds.

        The bound on a live event's latency through this driver, and the one
        number to state rather than discover: with back-pressure the pump keeps
        the ring full, so a note pressed now is heard after what is already in
        it has been handed out.
        """
        frames = len(self._ring) // self._frame_size
        return frames * 1000.0 / float(rate or 48000)

    def spawn(self, sample, status, loop=False):
        mod = module()
        self._status = status
        self._paced_by_ring = backpressure()
        mod.spawn(sample, _BLOCKS_FOREVER, status, ring=self._ring,
                  loop=loop, timeout_ms=200)
        if self._paced_by_ring:
            # Nothing to park. The pump runs until the ring is full and then
            # sleeps in the C loop, so it is already doing the only thing this
            # driver ever wanted it to do. spawn() sets the engine's "a pump is
            # live" flag on THIS thread before it returns, so running() is
            # already True and the first produce() cannot mistake a pump that
            # has not finished its first block for a dead one.
            self._parked = False
            if not mod.running():
                mod.shutdown()
                raise RuntimeError("the pump would not start")
            return
        # No back-pressure on this build: the pump would free-run and drop, so
        # it runs only inside produce(). park() returns True once the thread is
        # at a block boundary, which is also the handshake that says it
        # STARTED -- a produce() that arrived first used to read running() as
        # False and conclude the pump was dead, one silent round in a hundred
        # play-stop cycles.
        if not mod.park(200000):
            mod.shutdown()
            raise RuntimeError("the pump would not start")
        self._parked = True

    def dropped(self):
        """Blocks the ring had no room for. Must be 0; it is the byte stream."""
        status = self._status
        if status is None:
            return 0
        import struct

        return struct.unpack_from("<Q", status, 10 * 8)[0]

    def waited(self):
        """(times, microseconds) the pump waited for this driver to drain.

        Zero on a build with no back-pressure, and zero on one whose consumer
        is always slower than the ring is deep. It is the number that says the
        ring really is the pace: a pump that never waits is a pump nothing is
        holding back, and on a desktop that means it was dropping.
        """
        status = self._status
        if status is None or len(status) < 34 * 8:
            return (0, 0)
        import struct

        return struct.unpack_from("<QQ", status, 32 * 8)

    def produce(self, into):
        mod = module()
        if not self._paced_by_ring:
            mod.unpark()
            self._parked = False
        view = memoryview(into)
        at = 0
        idle = 0
        while at < len(view):
            # running() is read BEFORE the drain, and that ordering is the
            # whole of the fix: read it after, and a pump that finishes its
            # last block between the two says "stopped" while the block it
            # just wrote is still in the ring. The player then sees an empty
            # ring plus a stopped pump, calls it the end of the sample and
            # throws the block away. Two or three play() calls in a hundred
            # were silent, and nothing in the status block said why.
            live = mod.running()
            got = mod.drain(view[at:])
            if got:
                at += got
                idle = 0
                continue
            if at or not live:
                break
            # Nothing yet and nothing pulled: the pump has been unparked for
            # microseconds and has not finished its first block. Waiting here
            # beats returning a service call that produced nothing.
            idle += 1
            if idle > 20000:
                break
        self.rest()
        return at

    def rest(self):
        """Stop the pump running ahead until the next produce().

        A no-op where the ring is the pace: running ahead is exactly what the
        pump is supposed to do there, and it stops on its own when the ring is
        full. Parking it here would put the DSP back on the app's timeline,
        which is the cost this whole change exists to remove.
        """
        if self._paced_by_ring:
            return
        mod = module()
        if not self._parked and mod.running():
            mod.park(200000)
            self._parked = True

    def close(self):
        self._parked = False


class ServiceDriver(RingDriver):
    """WebAssembly: there is no thread, so this tick *is* the pump.

    Same ring, same drain, same bytes. What changes is where the loop runs:
    ``audiopump.service()`` enters the C pull loop on the interpreter thread
    and returns when the ring is full, so the park/unpark dance above has
    nothing to park -- the pump is at a block boundary whenever Python holds
    the thread, which is always.

    The ring stops being a buffer against a racing thread and becomes the
    **look-ahead**: everything produced in this tick has to last until the
    next one. A tick of T milliseconds therefore needs a ring longer than T,
    and measurably so -- 10 ms wants 4 blocks, 50 ms wants 16 and 200 ms
    wants 64 (``docs/spikes/probes/wasm_timer.py``). That is the whole of the
    difference a missing thread makes; the audio is byte-identical either way.
    """

    def __init__(self, frame_size, *, chunk_bytes=0, max_block=0, ahead_ms=0):
        super().__init__(frame_size, chunk_bytes=chunk_bytes,
                         max_block=max_block)
        # A ring that cannot hold what one tick must hand out will starve the
        # sink however fast the machine is, so the look-ahead is sized here
        # rather than discovered in a browser. RingDriver's own floor (four
        # blocks, eight drains) still applies -- this only ever grows it.
        if ahead_ms and frame_size:
            want = int(ahead_ms) * 48 * int(frame_size)
            if max_block:
                want = ((want + max_block - 1) // max_block) * max_block
            if want > len(self._ring):
                self._ring = bytearray(want)

    def spawn(self, sample, status, loop=False):
        mod = module()
        self._status = status
        mod.spawn(sample, _BLOCKS_FOREVER, status, ring=self._ring,
                  loop=loop, timeout_ms=200)
        # No park handshake: spawn() on this port adopts the tail and returns
        # without pulling a block, so there is nothing to wait for and
        # nothing to catch. The first service() below is the first audio.
        self._parked = False

    def produce(self, into):
        mod = module()
        view = memoryview(into)
        at = 0
        while at < len(view):
            # Fill first, then drain -- the opposite order to RingDriver's,
            # and it has to be: nothing else is going to fill it.
            packed = mod.service()
            why = packed & mod.SERVICE_MASK
            live = why != mod.SERVICE_DONE
            got = mod.drain(view[at:])
            if got:
                at += got
                continue
            if at or not live:
                break
            if why == mod.SERVICE_MORE and packed >> mod.SERVICE_SHIFT == 0:
                break
        return at

    def rest(self):
        """Nothing to rest. The pump only runs inside produce()."""


class BusioDriver(_Driver):
    """esp32: the graph goes to ``audiobusio.I2SOut``, and it owns the bus.

    **There is one way this firmware plays a sample**, and this is where
    :mod:`audiodev` joins it. ``I2SOut`` opens the channel, spawns the pump,
    converts anything that is not already signed 16-bit on the pump's thread,
    reads a file through a ring of its own, retunes the bus to the sample's
    rate on every ``play()``, sizes the DMA descriptor **in time** and refuses
    a second output with CircuitPython's own "Peripheral in use". None of that
    is ``audiodev``'s to reimplement, and all of it used to be: this class
    opened the channel with ``_audioif.i2s_start`` and a ``dma_frame=128``
    fixed at every rate, which is the descriptor bug ``audiobusio`` already
    measured and fixed (67 starved blocks in 2 s at 8 kHz; zero at ``rate/200``).

    What stays here is the policy nothing below the line knows about: the
    codec. ``I2SOut`` does not know a codec exists -- CircuitPython's does not
    either -- so the board's ``audio_power`` role is raised here, with the
    volume the transport is holding, and the transport is told its hardware is
    live so ``set_volume()`` and ``mute()`` reach the codec while the pump
    plays. That was measured on the P4 as a volume knob that stored a number
    and reached nothing.

    Two keywords of ``I2SOut``'s are ours rather than CircuitPython's and both
    are used here: ``port=`` (a board can have the codec on one port and a
    microphone on another) and ``main_clock_fs=`` (the board's ``I2SWire``
    has carried it since before this module existed). ``sink=`` is the third,
    and on a desktop it is what makes this class testable at all -- see
    :meth:`open`.
    """

    needs_service = False

    def __init__(self, wire, fmt, *, power=None, volume=100, transport=None):
        self.wire = wire
        self.fmt = fmt
        # The transport that published the wire. Nothing opens it on this
        # path, so it has to be told its codec is live or its set_volume()
        # and mute() go nowhere -- see PCMOutput.hardware_live.
        self.transport = transport
        self._power = power
        self.volume = int(volume)
        self.out = None

    def open(self):
        if self.out is not None:
            return
        mod = busio()
        if mod is None:
            raise RuntimeError("this firmware has no audiobusio.I2SOut")
        if self._power is not None:
            # With the volume where the board will take it. Nothing opens the
            # transport on this path, so PCMOutput.open()'s "apply the
            # hardware volume and mute" never runs and the codec would come up
            # at whatever the last thing to touch it left behind.
            try:
                self._power(True, volume=self.volume)
            except TypeError:
                self._power(True)
        w = self.wire
        kwargs = {"sample_rate": self.fmt.rate}
        port = getattr(w, "port", -1)
        if port is not None and int(port) >= 0:
            kwargs["port"] = int(port)
        mck_fs = getattr(w, "mck_fs", None)
        if mck_fs:
            kwargs["main_clock_fs"] = int(mck_fs)
        # A wire that names a file is a DESKTOP wire, and it is the whole of
        # how this class is proved without a board: `audiobusio` on unix is
        # the same object with the same lifecycle, paced off the wall clock,
        # writing where it is told. A board's I2SWire has no `sink` and this
        # never fires.
        sink = getattr(w, "sink", None)
        if sink is not None:
            kwargs["sink"] = sink
        try:
            self.out = mod.I2SOut(w.sck, w.ws, w.sd, main_clock=w.mck,
                                  **kwargs)
        except Exception:
            # The codec is up and nothing is going to play through it. Put it
            # back rather than leaving a board humming at whatever the rails
            # do with no clock on them.
            if self._power is not None:
                self._power(False)
            raise
        self._mark_transport(True)

    def _mark_transport(self, live):
        t = self.transport
        if t is not None and hasattr(t, "hardware_live"):
            t.hardware_live(live)

    def opened(self):
        return self.out is not None

    def spawn(self, sample, status, loop=False):
        self.open()
        self.out.play(sample, loop=loop)

    def retarget(self, sample, loop=False):
        # `I2SOut.retarget` rather than `audiopump.retarget` behind its back:
        # the output roots the graph it is playing, so swapping the tail
        # underneath it would leave `I2SOut` holding the OLD one and the new
        # one unrooted while a thread pulls it.
        self.out.retarget(sample, loop=loop)

    def halt(self):
        out = self.out
        if out is not None:
            out.stop()

    def playing(self):
        out = self.out
        return out is not None and out.playing

    def starved(self):
        """Blocks the DMA could not be given in time. ``I2SOut``'s own word."""
        out = self.out
        return 0 if out is None else out.starved()

    def status(self):
        out = self.out
        return None if out is None else out.status

    def close(self):
        out = self.out
        self.out = None
        self._mark_transport(False)
        if out is not None:
            try:
                out.deinit()      # stops, joins, and gives the channel back
            except Exception:     # noqa: BLE001 - a close must not raise into
                pass              # somebody else's teardown
        if self._power is not None:
            self._power(False)


class PumpOutput:
    """A push stream on the pump: ``PCMOutput``'s ``_write``, over a Ring.

    On **esp32** this is what a ``PCMOutput`` has to become, because the pump
    owns the I2S channel and ``machine.I2S`` cannot be opened beside it. The
    contract lines up exactly: ``audiopump.Ring.write()`` takes whole frames
    and returns bytes accepted, which is ``try_write()``'s, and ``space()`` is
    bytes, which is what the fill-to-space rule counts in.

    On a **desktop host it is not used, and that is the answer rather than an
    omission**: the transport there is already a push queue with its own
    thread behind it, so putting the pump in the middle would copy every byte
    into a ring and out again to reach the same queue, for nothing. The pump
    earns its place where it owns the peripheral or pulls a graph.

    Mix it into audiodev with::

        class MyOut(PCMOutput):
            def _write(self, buf):  return self._ring.write(buf)
            def space(self):        return self._ring.space()

    which is what :func:`attach_stream` builds.
    """

    def __init__(self, fmt, *, frames=256, capacity=6):
        mod = module()
        if mod is None or not hasattr(mod, "Ring"):
            raise RuntimeError("this firmware has no audiopump.Ring")
        self.format = fmt
        self.ring = mod.Ring(sample_rate=fmt.rate, channel_count=fmt.channels,
                             frames=frames, capacity=capacity)

    # A tick can land between `deinit()`'s first two lines, and an app whose
    # tick writes PCM would then find `self.ring` None and get an
    # AttributeError out of its own timer callback. A stream that has been
    # closed accepts nothing and holds nothing, which is what a caller can
    # act on; raising out of somebody's teardown is not.
    def write(self, buf):
        ring = self.ring
        return 0 if ring is None else ring.write(buf)

    def space(self):
        ring = self.ring
        return 0 if ring is None else ring.space()

    def level(self):
        ring = self.ring
        return 0 if ring is None else ring.level()

    def drain(self):
        """Nothing to do: the pump is the consumer and it never blocks."""
        return None

    def deinit(self):
        # Off the pump FIRST. A deinited Ring left registered as a client is
        # rebuilt into the next root Mixer, and audiomixer raises on it -- from
        # inside an unrelated player's close().
        _enter()
        try:
            ring = self.ring
            self.ring = None
            owner().stop(self)
        finally:
            _leave()
        if ring is not None:
            ring.deinit()


def attach_stream(fmt, *, driver=None, frames=256, capacity=6):
    """Put a push stream on the pump beside whatever else is sounding.

    Returns a :class:`PumpOutput` the caller writes PCM into, already
    registered as a pump client -- so an ``AudioOut`` graph and this stream
    are summed by a root Mixer and come out of one peripheral.
    """
    stream = PumpOutput(fmt, frames=frames, capacity=capacity)
    _enter()
    try:
        took = owner().play(stream, stream.ring, driver=driver)
    finally:
        _leave()
    if not took:
        stream.deinit()
        raise RuntimeError(owner().fault() or "the pump would not take it")
    return stream


class _Client:
    """One thing sounding through the pump, and whether it is paused."""

    __slots__ = ("owner", "sample", "paused", "loop")

    def __init__(self, owner, sample, loop=False):
        self.owner = owner
        self.sample = sample
        self.paused = False
        # Whose loop this is. A RawSample has no idea it is being looped --
        # CircuitPython puts the flag on the OUTPUT, and so does the pump --
        # so the client has to carry it or a looping sample plays one buffer
        # and stops. Which is exactly what a second client used to do to the
        # first: every mixer voice was hardcoded loop=False.
        self.loop = bool(loop)


class Pump:
    """The one pump, and who is sounding through it.

    Clients come and go with :meth:`play` and :meth:`stop`. One client is the
    pump's tail directly. A second client makes a root ``audiomixer.Mixer``
    with a voice each, at level 1.0 -- the Mixer *sums*, so two loud clients
    clip, which is the same arithmetic two CircuitPython ``AudioOut``\\ s into
    one DAC would do and is stated rather than quietly halved. The old root is
    retired one generation late, never deinited straight after the retarget:
    doing that immediately is a race the P4 caught, with fault=deinited.
    """

    def __init__(self):
        mod = module()
        self._status = bytearray(mod.STATUS_BYTES) if mod else bytearray(0)
        self._clients = []
        self._driver = None
        self._root = None
        self._retired = None
        self._spawned = False
        self._fault = None
        self._events = None

    # --- the clock -------------------------------------------------------

    def events(self, capacity=96):
        """The pump's event queue, or None on a build without a pump.

        One queue, for the same reason there is one pump: it is the pump that
        applies it, at the top of each block, on its own thread. An app puts
        notes on it with a frame number -- see ``Instrument.scheduled()`` in
        audioinstruments -- and the groove then stops caring what the
        interpreter thread is doing.

        **It is re-attached here rather than by the app**, because
        ``audiopump.shutdown()`` drops the queue along with the thread, and a
        player calling ``play()`` a second time goes through a shutdown.
        An app that attached its own queue once would find it quietly stopped
        being applied on the next kit change, with no error anywhere. It is
        also emptied at that point: every frame in it was stamped against a
        clock that has just gone back to zero.
        """
        mod = module()
        if mod is None or not hasattr(mod, "Events"):
            return None
        if self._events is None:
            self._events = mod.Events(capacity=capacity)
            self._attach_events()
        return self._events

    def _attach_events(self):
        """Hand the queue to the pump. Safe before spawn and after one."""
        mod = module()
        if mod is None or self._events is None:
            return
        try:
            self._events.clear()
            mod.events(self._events)
        except Exception:    # noqa: BLE001 - an app that never asked for a
            # queue must not lose its audio because one could not be attached
            pass

    # --- clients ---------------------------------------------------------

    def _find(self, owner):
        for client in self._clients:
            if client.owner is owner:
                return client
        return None

    def clients(self):
        return len(self._clients)

    def play(self, owner, sample, driver=None, loop=False):
        """Put *owner*'s *sample* on the pump. Returns True when it sounds."""
        _enter()
        try:
            return self._play(owner, sample, driver, loop)
        finally:
            _leave()

    def _play(self, owner, sample, driver, loop):
        if self._fault is not None:
            return False
        client = self._find(owner)
        if client is None:
            client = _Client(owner, sample, loop=loop)
            self._clients.append(client)
        else:
            client.sample = sample
            client.paused = False
            client.loop = bool(loop)
        if self._driver is None:
            self._driver = driver
        try:
            self._retarget()
        except Exception as exc:          # noqa: BLE001 - reported, not raised
            self._clients.remove(client)
            self._fault = str(exc)
            return False
        return True

    def stop(self, owner):
        _enter()
        try:
            self._stop(owner)
        finally:
            _leave()

    def _stop(self, owner):
        client = self._find(owner)
        if client is None:
            return
        self._clients.remove(client)
        if not self._clients:
            self.shutdown()
            return
        try:
            self._retarget()
        except Exception as exc:    # noqa: BLE001 - a client leaving must not
            # take the others' audio out with it, and it must not raise inside
            # somebody else's close().
            self._fault = str(exc)
            self.shutdown()

    def pause(self, owner):
        _enter()
        try:
            client = self._find(owner)
            if client is not None:
                client.paused = True
            self._settle()
        finally:
            _leave()

    def resume(self, owner):
        _enter()
        try:
            client = self._find(owner)
            if client is not None:
                client.paused = False
            self._settle()
        finally:
            _leave()

    def paused(self):
        return bool(self._clients) and all(c.paused for c in self._clients)

    def _settle(self):
        """Park while everything is paused; unpark when something is not."""
        mod = module()
        if mod is None or not self._spawned:
            return
        if self.paused():
            mod.park(200000)
        else:
            mod.unpark()

    # --- the graph -------------------------------------------------------

    def _tail(self):
        if len(self._clients) == 1:
            return self._clients[0].sample
        import audiomixer

        first = self._clients[0].sample
        mixer = audiomixer.Mixer(
            voice_count=len(self._clients),
            sample_rate=first.sample_rate,
            channel_count=first.channel_count,
            bits_per_sample=first.bits_per_sample,
            samples_signed=True,
            buffer_size=first.max_buffer_length * 2
            if hasattr(first, "max_buffer_length")
            else 2048,
        )
        for voice, client in enumerate(self._clients):
            mixer.voice[voice].level = 1.0
            mixer.play(client.sample, voice=voice, loop=client.loop)
        return mixer

    def _retarget(self):
        mod = module()
        old_root = self._root
        tail = self._tail()
        self._root = tail if tail is not self._clients[0].sample else None
        # One client IS the tail, so its loop is the pump's; a Mixer never
        # says DONE, so a mixer tail never wants one and each voice carries
        # its own instead.
        loop = self._root is None and self._clients[0].loop
        if self._spawned and mod.running():
            # The LIVE branch: a client arriving at, or leaving, a pump that
            # is still sounding. No gap, no re-open, and on a board no codec
            # power cycle -- which is the whole reason a kit change does not
            # click. `loop` travels with the tail; for as long as it did not,
            # a looping client left alone here stopped at the end of its lap.
            if self._driver is not None:
                self._driver.retarget(tail, loop=loop)
            else:
                retarget(mod, tail, loop)
            self._release_retired()
            self._retired = old_root
            return
        if self._spawned:
            # A pump that stopped by itself still holds its task and its I2S
            # channel, and spawn() refuses it with "a pump is already spawned".
            # Between the laps of a looping sample that window is wide open,
            # and a second client arriving in it hit exactly that.
            if self._driver is not None:
                self._driver.halt()
            else:
                mod.shutdown()
            self._spawned = False
        self._release_retired()
        self._retired = old_root
        for i in range(len(self._status)):
            self._status[i] = 0
        if self._driver is not None:
            self._driver.spawn(tail, self._status, loop=loop)
        else:
            mod.spawn(tail, _BLOCKS_FOREVER, self._status, loop=loop,
                      timeout_ms=200)
        self._spawned = True
        # The teardown above took the queue with it. See Pump.events().
        self._attach_events()

    def _release_retired(self):
        retired = self._retired
        self._retired = None
        if retired is None:
            return
        deinit = getattr(retired, "deinit", None)
        if deinit is not None:
            try:
                deinit()
            except Exception:   # noqa: BLE001 - a retired root, nothing to do
                pass

    # --- what the pump made ----------------------------------------------

    def produce(self, into):
        if self._driver is None or not self._spawned:
            return 0
        return self._driver.produce(into)

    def rest(self):
        driver = self._driver
        if driver is not None and hasattr(driver, "rest"):
            driver.rest()

    def status(self):
        """The block the loop writes. The DRIVER's, where it owns one.

        ``audiobusio.I2SOut`` spawns with a status bytearray of its own, so on
        a board the one this object allocated is never written to. Reading it
        anyway is the shape of bug that reports a healthy pump as
        ``error 0, fault 0`` for ever -- silence with a reassuring sentence.
        """
        driver = self._driver
        if driver is not None:
            owned = driver.status()
            if owned is not None:
                return owned
        return self._status

    def died(self):
        """The reason the pump stopped by itself, as a sentence, or None."""
        mod = module()
        if mod is None or not self._spawned or mod.running():
            return None
        import struct

        status = self.status()
        w = struct.unpack("<%dQ" % mod.STATUS_WORDS, status)
        why = _FAULTS.get(w[24]) or _ERRORS.get(w[5])
        return why or "the pump stopped (error %d, fault %d)" % (w[5], w[24])

    def fault(self):
        """The reason the pump is not usable for the rest of this process."""
        return self._fault

    def note_fault(self, why):
        self._fault = why

    def shutdown(self):
        _enter()
        try:
            self._shutdown()
        finally:
            _leave()

    def _shutdown(self):
        mod = module()
        self._clients = []
        self._root = None
        self._release_retired()
        driver = self._driver
        if self._spawned and mod is not None:
            # Through the driver: on a board the pump belongs to the I2SOut,
            # and calling audiopump.shutdown() behind it leaves that object
            # believing it is still playing until something reads `playing`.
            if driver is not None:
                driver.halt()
            else:
                mod.shutdown()
        self._spawned = False
        self._driver = None
        if driver is not None:
            driver.close()


_owner = None


def owner():
    """The process's one :class:`Pump`."""
    global _owner
    if _owner is None:
        _owner = Pump()
    return _owner


def forget():
    """Drop the pump and everything on it. For tests and soft-reset paths."""
    global _owner
    if _owner is not None:
        try:
            _owner.shutdown()
        except Exception:    # noqa: BLE001
            pass
    _owner = None
