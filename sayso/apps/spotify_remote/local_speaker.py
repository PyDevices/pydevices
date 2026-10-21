"""Optional local Spotify Connect speaker, so the remote can play on itself.

When the interpreter has the earful usermod, start() makes this process a
Connect speaker under the given name. It then shows up in the Devices panel
like any other speaker. Audio goes out through audiodev on the VM thread,
pumped from an LVGL timer: earful's C thread fills its PCM ring, and only
this thread may write to the audio output.

When this earful posts state events (Device.events()), the speaker drains
them on the same timer and hands them to on_events, so while it is the active
device the remote can follow it without asking the Web API (now_playing()).

Pairing is earful's: the phone pairs once over Zeroconf and earful keeps the
credentials. On a host its C side reads them from ~/.earful/credentials (or
earful.credentials in the working directory). On a board, Python hands them
over from earful.credentials, because the C side cannot reach the VFS.
"""

import sys

import lvgl as lv
from multimer import ticks_add, ticks_diff, ticks_ms

PUMP_MS = 10
CRED_FILE = "earful.credentials"
# On a board with audiodev's audio pump, how much PCM its ring holds. The pump
# plays from it on its own task; this thread only tops it up, so the UI can
# stall this long (a redraw, a Web API call) without a gap.
PUMP_RING_SECONDS = 4
# How long to wait for a hosted USB sound card to enumerate.
USB_FIND_MS = 15000
# The USB host ring between earful and the bus. When the speaker offers a C
# sink, earful drains into it from its own task, so the ring no longer has to
# outlast the interpreter's stalls -- earful's ~5 s ring does that -- and what
# it holds plays after a pause or a skip, so it is short: at 2 s, pause took
# 2 s to be heard on the LCD-7 (2026-09-25). Without one, this thread feeds
# the ring and it must hold the longest stall.
USB_RING_MS = 400
USB_RING_VM_MS = 2000
# earful stamps what it tells Spotify with the wall clock; hours off, the
# phone showed a playing speaker stopped at 0:00 (LCD-7, 2026-09-25: a serial
# tool had set the RTC to local time). A board syncs NTP at Wi-Fi connect;
# the speaker syncs again this often.
NTP_RESYNC_MS = 60 * 60 * 1000


def _load_board_credentials(earful):
    if sys.platform != "esp32":
        return
    try:
        with open(CRED_FILE, "rb") as file:
            earful.set_credentials(file.read())
    except OSError:
        print("local speaker: no %s; pair once from the phone" % CRED_FILE)


class _PumpPCM:
    """earful's view of an audiodev pump stream.

    earful's attach() calls write/space/service/set_volume as real methods
    (it looks them up in C, so no __getattr__). The pump's C task drains the
    ring into I2S; the board transport is never opened -- the pump owns the
    peripheral -- and is kept only for its codec volume.
    """

    def __init__(self, stream, transport, driver):
        self._stream = stream
        self._transport = transport
        self.driver = driver

    def write(self, buf):
        return self._stream.write(buf)

    def space(self):
        return self._stream.space()

    def queued_size(self):
        return self._stream.level()

    def service(self):
        pass

    def set_volume(self, volume):
        self._transport.set_volume(volume)

    def open(self):
        pass

    def close(self):
        self._stream.deinit()


def _pump_output(fmt):
    """A pump stream on this board, or None to use the board's pcm_out()."""
    try:
        from audiodev import pump
    except ImportError:
        return None
    mod = pump.module()
    if mod is None or not hasattr(mod, "Ring") or not pump.on_board():
        return None
    from boarddev import pcm_out

    # The transport publishes the board's I2S pins and codec power; find it
    # the way audiodev's AudioOut does, through any wrappers.
    transport = pcm_out(fmt)
    while transport is not None and getattr(transport, "wire", None) is None:
        transport = getattr(transport, "_inner", None)
    if transport is None:
        return None
    driver = pump.BusioDriver(
        transport.wire,
        fmt,
        power=getattr(transport, "audio_power", None),
        volume=transport.volume,
        transport=transport,
    )
    frames = 256
    capacity = max(2, fmt.rate * PUMP_RING_SECONDS // frames)
    stream = pump.attach_stream(fmt, driver=driver, frames=frames, capacity=capacity)
    print("local speaker: audio pump, %d s ring" % PUMP_RING_SECONDS)
    return _PumpPCM(stream, transport, driver)


class _UsbPCM:
    """earful's view of a hosted USB sound card (usb.host.audio's Speaker).

    The host drains the ring onto the bus in real time. earful writes at most
    space(), and a write never waits for the bus, so a full ring can never
    stall the UI. The card's volume is earful's own: it scales the samples it
    writes, so set_volume has nothing to do here.
    """

    def __init__(self, speaker):
        self._spk = speaker
        if hasattr(speaker, "c_sink"):
            # earful drains into this from its own task, so the VM no longer
            # moves the bytes. Without it earful keeps its VM pump.
            self.c_sink = speaker.c_sink

    def write(self, buf):
        return self._spk.write(buf)

    def space(self):
        return self._spk.space()

    def queued_size(self):
        return self._spk.queued()

    def service(self):
        pass

    def set_volume(self, volume):
        pass

    def open(self):
        self._spk.start()

    def close(self):
        import usb.core

        self._spk.stop()
        usb.core.stop()


def _usb_output(fmt):
    """A hosted USB sound card at fmt, or None when there is none.

    No resampling: the card must offer fmt's rate (earful's is 44.1 kHz), and
    Speaker raises, listing what the card does offer, if it doesn't.
    """
    try:
        import time

        import usb.core
        from usb.host.audio import Speaker
    except ImportError:
        print("local speaker: this firmware has no usb-core and usb-host-audio for a USB sound card")
        return None
    usb.core.start(classes=("uac",))
    ring_ms = USB_RING_MS if hasattr(Speaker, "c_sink") else USB_RING_VM_MS
    deadline = ticks_add(ticks_ms(), USB_FIND_MS)
    while ticks_diff(deadline, ticks_ms()) > 0:
        dev = usb.core.find(custom_match=Speaker.match)
        if dev is not None:
            try:
                out = Speaker(dev, rate=fmt.rate, channels=fmt.channels, bits=fmt.bits, ring_ms=ring_ms)
            except ValueError as error:
                # Says what the card does offer.
                usb.core.stop()
                print("local speaker: USB sound card unusable: %s" % (error,))
                return None
            print("local speaker: USB sound card, %s" % (dev.product,))
            return _UsbPCM(out)
        time.sleep_ms(250)
    usb.core.stop()
    print("local speaker: no USB sound card found")
    return None


class LocalSpeaker:
    def __init__(self, earful, name, device, pcm, fmt):
        self.name = name
        self.device = device
        self._earful = earful
        self._pcm = pcm
        self._service = getattr(device, "service", None)
        # 10 ms of silence keeps a queued host sink ticking until playback.
        self._silence = bytes(fmt.frame_size * fmt.rate * PUMP_MS // 1000)
        self._host = sys.platform != "esp32"
        self._saved = earful.has_credentials()
        self._ticks = 0
        # earful's state events, where this build has them: a call that
        # returns an empty tuple, without allocating, while nothing changes.
        self._events = getattr(device, "events", None)
        self.has_events = self._events is not None
        # True while this speaker is Spotify's active device, by its events.
        self.active = False
        # Called on the VM thread with each batch: [(kind, value), ...].
        self.on_events = None
        self._timer = lv.timer_create(self._pump, PUMP_MS, None)
        self._ntp_timer = None
        if sys.platform == "esp32":
            self._ntp_timer = lv.timer_create(self._ntp, NTP_RESYNC_MS, None)

    def _ntp(self, _timer):
        try:
            import ntptime

            ntptime.timeout = 1  # one short UDP exchange on this thread
            ntptime.settime()
        except Exception as error:  # noqa: BLE001 - try again next hour
            print("local speaker: ntp %r" % (error,))

    def _pump(self, _timer):
        if self._service is not None:
            self._service()
        # Queued host sinks stall without a keepalive; a board's I2S does not
        # queue (queued_size() is 0), so it gets none.
        if self._host and not self.device.playing:
            if self._pcm.queued_size() < 4 * len(self._silence):
                self._pcm.write(self._silence)
        self._pcm.service()
        if self._events is not None:
            events = self._events()
            if events:
                for kind, value in events:
                    if kind == "active":
                        self.active = bool(value)
                if self.on_events is not None:
                    self.on_events(events)
        self._ticks += 1
        if self._ticks % 100 == 0:
            self._save_board_credentials()

    def _save_board_credentials(self):
        # A board keeps the pairing only if Python writes it; once per run.
        if self._saved or sys.platform != "esp32" or not self._earful.has_credentials():
            return
        self._saved = True
        try:
            with open(CRED_FILE, "wb") as file:
                file.write(self._earful.credentials())
        except OSError as error:
            print("local speaker: credentials not saved: %r" % (error,))

    def now_playing(self, base=None, events=()):
        """The remote's now-playing state, as earful has it.

        base is the last state shown: what earful can't know (whether the
        track is saved, its artists' ids, the context) is kept from it while
        the track is the same and cleared when it changes. events are the
        (kind, value) pairs that prompted this; their values win over the
        device's attributes, which can lag a skip by a moment. Art is the
        URL only: the caller turns it into a cached file off the UI thread.
        """
        dev = self.device
        state = dict(base or {})
        uri = dev.track
        if uri != state.get("item_uri"):
            for key in ("saved", "album_saved", "album_id", "album_uri", "art_path"):
                state[key] = None
            state["artists"] = ()
        state["item_uri"] = uri
        state["item_id"] = uri.rsplit(":", 1)[-1] if uri else None
        state["item_type"] = uri.split(":")[1] if uri and uri.count(":") >= 2 else None
        state["track"] = dev.title or ""
        state["artist"] = dev.artist or ""
        state["album"] = dev.album or ""
        state["art_url"] = dev.art
        playing = bool(dev.playing)
        position = dev.position or 0
        duration = dev.duration or 0
        for kind, value in events:
            if kind == "playing":
                playing = bool(value)
            elif kind == "position":
                position = value
            elif kind == "track" and value:
                duration = value
        state["playing"] = playing
        state["progress_ms"] = position
        state["duration_ms"] = duration
        state["volume"] = dev.volume
        if state.get("device") != self.name:
            state["device_id"] = None
        state["device"] = self.name
        return state

    def stop(self):
        self._timer.delete()
        if self._ntp_timer is not None:
            self._ntp_timer.delete()
        self.device.stop()
        self._pcm.close()


def start(name, bitrate=160, output=None, volume=None):
    """Start a Connect speaker named name; return a LocalSpeaker or None.

    output: None for this machine's own audio (the board's, through the audio
    pump where the firmware has it, or the host's), "usb" for a hosted USB
    sound card (an S3 without a codec driving a board that is a USB speaker).
    volume: the speaker's volume (0-100) before anything sets one; None keeps
    earful's default (100).
    """
    try:
        import earful
    except ImportError:
        print("local speaker: this interpreter has no earful module")
        return None
    if not earful.available():
        print("local speaker: earful is not available on this port")
        return None

    from audiodev import AudioFormat
    from boarddev import pcm_out

    # Spotify's PCM: 44.1 kHz stereo 16-bit. The default (buffered) host
    # profile rides out the pauses while the UI waits on the Web API.
    fmt = AudioFormat(44100, 2, 16)
    if output == "usb":
        pcm = _usb_output(fmt)
        if pcm is None:
            return None
    else:
        pcm = _pump_output(fmt)
        if pcm is None:
            pcm = pcm_out(fmt)
    pcm.open()
    _load_board_credentials(earful)
    device = earful.Device(name=name, bitrate=bitrate)
    if volume is not None:
        # Before start(): earful hands it to the session, which reports it
        # to Spotify and scales the audio by it.
        device.volume = volume
    device.start()
    device.attach(pcm)
    print("local speaker: %s started" % name)
    return LocalSpeaker(earful, name, device, pcm, fmt)
