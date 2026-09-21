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

``SinkDriver``
    esp32. The pump owns the I2S channel outright (``_audioif.i2s_start``
    from the board's :class:`~audiodev.I2SWire`, never ``machine.I2S``) and
    writes each block into the DMA on its own thread, with no Python in the
    path at all. An ESP32-P4 has played through it; see
    ``docs/spikes/live-audio-path-notes.md`` in the workspace anchor for what
    that sitting measured and the three defects it gave up.

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
        """Top the ring up. Returns bytes written this call."""
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
    """Where the pump's blocks go. Subclassed per port."""

    needs_service = True

    def spawn(self, sample, status):
        raise NotImplementedError

    def produce(self, into):
        """Fill *into* with what the pump has made. Returns bytes."""
        return 0

    def opened(self):
        return True

    def close(self):
        pass


class RingDriver(_Driver):
    """Desktop: the pump fills a RAM ring, the interpreter drains it.

    Nothing on a desktop paces the pump -- there is no DMA to block on -- so a
    free-running pump fills the ring in a few milliseconds and the C ring then
    *drops* whole blocks (``STATUS_RING_OVF``) rather than overwriting what has
    not been taken. A dropped block is not a glitch you can hear past on a WAV
    recording; it is a hole in the bytes.

    So this driver unparks the pump only *inside* :meth:`produce` and parks it
    again before returning. The window is one drain, the ring only has to
    absorb what the pump makes while the interpreter is copying bytes out of
    it, and the stream is exact -- ``STATUS_RING_OVF`` stays at 0, which is the
    number that says so.

    **What that costs, and what it would be worth not to.** A parked pump is a
    pump the interpreter *waits* for, so on the desktop the DSP is back on the
    app's timeline however many threads it runs on: 5 s of a synth through two
    effects cost an idle app 817 ms on the old path and 866 ms on this one, and
    96 % of the pump path's time is inside produce(), waiting. Letting the pump
    run between ticks instead was tried, with a policy that stopped the moment
    the ring reported a drop. An app doing 3.5 ms of its own work per tick went
    from 1811 ms to 1028 ms -- **1.8x**, the DSP genuinely overlapping the
    drawing -- and the audio lost 71 to 5657 blocks and diverged 160 ms in,
    every time. The policy cannot work: by the time ``STATUS_RING_OVF`` says a
    block was dropped, the block is gone.

    The one change that wins it properly is in C, and it is small:
    ``audiopump.c``'s **output ring drops on overflow rather than making the
    pump wait**. A ring that blocked the pump would pace it exactly as an I2S
    write paces it on a board, no park would be needed, and the desktop would
    get the 1.8x with no byte at risk. That ring is the board agent's file and
    its 64-bit cross-thread counters are already owed a fix; this belongs in
    the same pass.
    """

    def __init__(self, frame_size, *, chunk_bytes=0, max_block=0):
        # The floor is one block of the graph, and a graph's block is whatever
        # its tail offers: an audiocore.RawSample hands back its ENTIRE buffer
        # in one call, so a half-second tone is a 96 kB "block". A ring shorter
        # than that can never hold one, and the C ring DROPS what it cannot
        # hold -- silent, total loss of that block, not a glitch you can hear
        # past. Four blocks, or four drains, whichever is larger.
        want = max(4 * int(max_block or 0), 8 * int(chunk_bytes or 0),
                   64 * int(frame_size))
        self._ring = bytearray(want)
        self._parked = False
        self._status = None

    def spawn(self, sample, status):
        mod = module()
        self._status = status
        mod.spawn(sample, _BLOCKS_FOREVER, status, ring=self._ring, timeout_ms=200)
        # Park immediately: from here on the pump runs only inside produce().
        # park() returns True once the thread is at a block boundary, so this
        # is also the handshake that says it STARTED -- spawn() returns before
        # the thread has run a line, and a produce() that arrives first reads
        # running() as False and concludes the pump is dead. That was one
        # silent round in a hundred play-stop cycles.
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

    def produce(self, into):
        mod = module()
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
        """Stop the pump running ahead until the next produce()."""
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

    def spawn(self, sample, status):
        mod = module()
        self._status = status
        mod.spawn(sample, _BLOCKS_FOREVER, status, ring=self._ring,
                  timeout_ms=200)
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


class SinkDriver(_Driver):
    """esp32: the pump writes each block straight into the I2S DMA.

    The pump owns the peripheral. ``machine.I2S`` must never be opened on the
    same port -- two owners of one I2S channel is the failure that sounds like
    silence -- so the transport's own ``open()`` is bypassed and the port is
    opened here from the board's :class:`~audiodev.I2SWire`, with the codec
    powered through the board's ``audio_power`` role.

    An ESP32-P4 has played through this. What the sitting cost: the volume
    knob and the mute button were reaching nothing, because
    ``PCMOutput.set_volume`` was guarded on ``is_open`` and nothing opens the
    transport on this path -- :meth:`open` calls ``hardware_live()`` now, and
    that is the whole of the fix.
    """

    needs_service = False

    def __init__(self, wire, fmt, *, power=None, volume=100, dma_desc=4,
                 dma_frame=128, din=-1, transport=None):
        self.wire = wire
        self.fmt = fmt
        # The transport that published the wire. Nothing opens it on this
        # path, so it has to be told its codec is live or its set_volume()
        # and mute() go nowhere -- see PCMOutput.hardware_live.
        self.transport = transport
        self._power = power
        self.volume = int(volume)
        self.dma_desc = int(dma_desc)
        self.dma_frame = int(dma_frame)
        self.din = int(din)
        self.cushion = 0
        self._open = False

    def open(self):
        if self._open:
            return
        mod = module()
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
        self.cushion = driver().i2s_start(
            w.port, w.sck, w.ws, w.sd, self.fmt.rate,
            bits=self.fmt.bits, channels=self.fmt.channels,
            mclk=-1 if w.mck is None else w.mck, mclk_fs=w.mck_fs,
            dma_desc=self.dma_desc, dma_frame=self.dma_frame, din=self.din,
        )
        self._open = True
        self._mark_transport(True)

    def _mark_transport(self, live):
        t = self.transport
        if t is not None and hasattr(t, "hardware_live"):
            t.hardware_live(live)

    def opened(self):
        return self._open

    def spawn(self, sample, status):
        self.open()
        module().spawn(sample, _BLOCKS_FOREVER, status, sink=True,
                       timeout_ms=500)

    def close(self):
        # shutdown() closes the channel with the task, so this only has to
        # undo what open() did that shutdown does not.
        self._open = False
        self._mark_transport(False)
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

    def write(self, buf):
        return self.ring.write(buf)

    def space(self):
        return self.ring.space()

    def level(self):
        return self.ring.level()

    def drain(self):
        """Nothing to do: the pump is the consumer and it never blocks."""
        return None

    def deinit(self):
        # Off the pump FIRST. A deinited Ring left registered as a client is
        # rebuilt into the next root Mixer, and audiomixer raises on it -- from
        # inside an unrelated player's close().
        ring = self.ring
        self.ring = None
        owner().stop(self)
        if ring is not None:
            ring.deinit()


def attach_stream(fmt, *, driver=None, frames=256, capacity=6):
    """Put a push stream on the pump beside whatever else is sounding.

    Returns a :class:`PumpOutput` the caller writes PCM into, already
    registered as a pump client -- so an ``AudioOut`` graph and this stream
    are summed by a root Mixer and come out of one peripheral.
    """
    stream = PumpOutput(fmt, frames=frames, capacity=capacity)
    if not owner().play(stream, stream.ring, driver=driver):
        stream.deinit()
        raise RuntimeError(owner().fault() or "the pump would not take it")
    return stream


class _Client:
    """One thing sounding through the pump, and whether it is paused."""

    __slots__ = ("owner", "sample", "paused")

    def __init__(self, owner, sample):
        self.owner = owner
        self.sample = sample
        self.paused = False


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

    def play(self, owner, sample, driver=None):
        """Put *owner*'s *sample* on the pump. Returns True when it sounds."""
        if self._fault is not None:
            return False
        client = self._find(owner)
        if client is None:
            client = _Client(owner, sample)
            self._clients.append(client)
        else:
            client.sample = sample
            client.paused = False
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
        client = self._find(owner)
        if client is not None:
            client.paused = True
        self._settle()

    def resume(self, owner):
        client = self._find(owner)
        if client is not None:
            client.paused = False
        self._settle()

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
            mixer.play(client.sample, voice=voice, loop=False)
        return mixer

    def _retarget(self):
        mod = module()
        old_root = self._root
        tail = self._tail()
        self._root = tail if tail is not self._clients[0].sample else None
        if self._spawned and mod.running():
            mod.retarget(tail)
            self._release_retired()
            self._retired = old_root
            return
        if self._spawned:
            # A pump that stopped by itself still holds its task and its I2S
            # channel, and spawn() refuses it with "a pump is already spawned".
            # Between the laps of a looping sample that window is wide open,
            # and a second client arriving in it hit exactly that.
            mod.shutdown()
            self._spawned = False
        self._release_retired()
        self._retired = old_root
        for i in range(len(self._status)):
            self._status[i] = 0
        if self._driver is not None:
            self._driver.spawn(tail, self._status)
        else:
            mod.spawn(tail, _BLOCKS_FOREVER, self._status, timeout_ms=200)
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
        return self._status

    def died(self):
        """The reason the pump stopped by itself, as a sentence, or None."""
        mod = module()
        if mod is None or not self._spawned or mod.running():
            return None
        import struct

        w = struct.unpack("<%dQ" % mod.STATUS_WORDS, self._status)
        why = _FAULTS.get(w[24]) or _ERRORS.get(w[5])
        return why or "the pump stopped (error %d, fault %d)" % (w[5], w[24])

    def fault(self):
        """The reason the pump is not usable for the rest of this process."""
        return self._fault

    def note_fault(self, why):
        self._fault = why

    def shutdown(self):
        mod = module()
        self._clients = []
        self._root = None
        self._release_retired()
        if self._spawned and mod is not None:
            mod.shutdown()
        self._spawned = False
        driver = self._driver
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
