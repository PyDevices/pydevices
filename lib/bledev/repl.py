"""The MicroPython REPL over Bluetooth, behind a password.

On the board, opt in from ``main.py`` (nothing starts it for you)::

    import bledev.repl
    bledev.repl.start(password="correct horse")   # or webrepl_cfg.PASS

The board then advertises the Nordic UART service as ``name`` while the normal
REPL carries on. A client connects, sends an empty line to get
``Password: ``, sends the password and a newline, and gets the prompt. From a
laptop or another board::

    import bledev.repl
    link = await bledev.repl.connect(ble, "correct horse", name="mpy-repl")
    await link.write(b"1 + 1\\r")

It behaves like WebREPL: one attempt per connection, a wrong password gets
``Access denied`` and a disconnect, and nothing the client sends reaches the
REPL before the password is right. Like WebREPL, the link isn't encrypted, so
someone sniffing nearby can capture the password.

**Pairing** encrypts the link, and bonds so the next connection skips it.
It's off unless you ask (``pairing=None``, the password alone):

* ``pairing="passkey"``: the board shows a six-digit passkey on its display
  (or the console) and the host types it in. That authenticates the host, so
  the password becomes optional: ``password=False`` drops it.
* ``pairing="justworks"``: encrypted and bonded, with no passkey. It proves
  nothing about who paired, so the password stays required; what it buys is
  that nobody sniffing can read the password or the session.
* ``pairing="numeric"``: both sides show a number; ``confirm(number)`` on the
  board says whether they match (a button, say).
* ``pairing="auto"``: ``"passkey"`` on a board with a display, else ``"justworks"``.

The keys live in NVS on an ESP32, so a filesystem erase keeps them and a full
chip erase loses them (``bledev.security``). A client pairs with
``connect(..., pair=True, passkey=...)``.

**The REPL owns the radio while it runs.** It registers its own GATT service
(replacing any other) and advertises whenever nobody is connected. It works
from interrupts rather than asyncio, so it keeps serving at the ``>>>``
prompt and while your program runs, and Ctrl-C interrupts a running program
as it does over USB. ``stop()`` gives the radio back. It's MicroPython only;
``connect()`` runs anywhere bledev does.
"""

import struct
import sys

from . import BLEError, GattError, NEEDS_PAIRING, PairingError, STALE_BOND, pack_advertisement, wait_ms
from . import nus

# bluetooth.BLE characteristic flags for the protected characteristics.
_F_READ_ENC = 0x0200
_F_READ_AUTHN = 0x0400
_F_WRITE_ENC = 0x1000
_F_WRITE_AUTHN = 0x2000

PROMPT = b"Password: "

# How often the server retries output the controller couldn't take yet.
_TICK_MS = 5
# With pairing on, how long a link may stay unpaired before the board hangs
# up, so a host that never pairs can't hold the one connection. SMP's own
# timeout is 30 s.
PAIR_WITHIN_MS = 30000
BANNER = b"\r\nbledev REPL connected\r\n>>> "
DENIED = b"\r\nAccess denied\r\n"

#: Longest password line the board will buffer before refusing.
MAX_PASSWORD = 64


class AuthError(BLEError):
    """The board refused the password."""


def _check_password(given, want):
    """Constant-time comparison of two byte strings."""
    diff = len(given) ^ len(want)
    for i in range(len(given)):
        diff |= given[i] ^ want[i % len(want)] if want else 1
    return diff == 0


class Login:
    """The password exchange, without a radio, so it can be tested anywhere.

    Feed it what the client writes. It answers with bytes to send back and a
    verdict: ``None`` while waiting, ``True`` with any bytes that followed the
    password (they go to the REPL), or ``False`` for a refusal.
    """

    def __init__(self, password):
        self._password = password.encode() if isinstance(password, str) else bytes(password)
        self._line = bytearray()
        self.verdict = None

    def feed(self, data):
        """``(reply, verdict, rest)`` for a chunk the client wrote."""
        if self.verdict is not None:
            return b"", self.verdict, b""
        reply = b""
        for i in range(len(data)):
            b = data[i]
            if b in (10, 13):
                if not self._line:
                    reply = PROMPT  # an empty line asks for the prompt; no attempt used
                    continue
                self.verdict = _check_password(bytes(self._line), self._password)
                self._line = bytearray()
                rest = bytes(data[i + 1 :])
                if self.verdict:
                    # Drop the other half of a CRLF so the REPL doesn't see a blank line.
                    if b == 13 and rest[:1] == b"\n":
                        rest = rest[1:]
                    return BANNER, True, rest
                return DENIED, False, b""
            if len(self._line) >= MAX_PASSWORD:
                self.verdict = False
                return DENIED, False, b""
            self._line.append(b)
        return reply, None, b""


# ---------------------------------------------------------------- the board side

_server = None


def start(
    password=None,
    name="mpy-repl",
    *,
    interval_us=100000,
    dupterm_index=0,
    files=False,
    console=True,
    window=None,
    pairing=None,
    show=None,
    hide=None,
    confirm=None,
    bond_store=None,
):
    """Serve the REPL over BLE until :func:`stop` or a reset. MicroPython only.

    ``password`` defaults to ``webrepl_cfg.PASS`` when that file exists;
    it must be at least 4 characters. Returns at once.

    ``files=True`` also serves :mod:`bledev.filetransfer` (CircuitPython's
    file-transfer service) behind the same password, with ``window`` bytes
    of free space per round trip; ``console=False`` leaves the REPL out.

    ``pairing`` is ``None`` (the default: the password alone), ``"passkey"``,
    ``"justworks"``, ``"numeric"`` or ``"auto"`` (see the module notes).
    With a pairing that authenticates (passkey, numeric), ``password=False``
    serves without one. ``show(passkey)``/``hide()`` replace drawing the
    passkey on ``board_config.display_drv``; ``confirm(number)`` answers
    numeric comparison. ``bond_store`` is where the keys go
    (``bledev.security.use_store``; default NVS on an ESP32).
    """
    global _server
    if sys.implementation.name != "micropython":
        raise BLEError("bledev.repl serves only on MicroPython; use connect() on this host")
    mode = None
    if pairing is not None:
        from . import security

        # Before the radio starts where possible, so its keys load first.
        security.use_store(bond_store)
        mode = security.configure(pairing, show=show, hide=hide, confirm=confirm)
    authenticates = mode in ("passkey", "numeric")
    if password is None:
        try:
            import webrepl_cfg

            password = webrepl_cfg.PASS
        except (ImportError, AttributeError):
            if not authenticates:
                raise ValueError("bledev.repl needs a password (or webrepl_cfg.PASS)")
            password = False
    if password is False or password == "":
        if not authenticates:
            raise ValueError(
                "only a pairing that authenticates the host (passkey, numeric) can replace the password"
            )
        password = None
    elif len(password) < 4:
        raise ValueError("the password must be at least 4 characters")
    if not (files or console):
        raise ValueError("nothing to serve: files=False and console=False")
    stop()
    _server = _Server(password, name, interval_us, dupterm_index, files, console, window, mode)
    _server.start()
    return _server


def stop():
    """Stop serving: drop the client, give the REPL back, stop advertising."""
    global _server
    if _server is not None:
        _server.stop()
        _server = None


def is_running():
    return _server is not None


try:
    import io

    _IOBase = io.IOBase
except (ImportError, AttributeError):  # CPython without the MicroPython stream protocol
    _IOBase = object


class _Stream(_IOBase):
    """What ``os.dupterm`` reads from and writes to."""

    def __init__(self, server):
        self._s = server

    def readinto(self, buf):
        s = self._s
        n = len(s.rx) - s.rx_pos
        if n <= 0:
            return None  # nothing yet; 0 would mean end of stream and detach us
        n = min(n, len(buf))
        buf[:n] = s.rx[s.rx_pos : s.rx_pos + n]
        s.rx_pos += n
        if s.rx_pos >= len(s.rx):
            s.rx = bytearray()
            s.rx_pos = 0
        return n

    def write(self, buf):
        self._s.send(buf)
        return len(buf)

    def ioctl(self, op, arg):
        if op == 3:  # MP_STREAM_POLL
            return 1 if (arg & 1) and len(self._s.rx) > self._s.rx_pos else 0
        return 0


class _Server:
    # Output buffered beyond this waits for the link before print() returns.
    TX_CAP = 4096
    # Input buffered beyond this, while nothing reads stdin, is dropped.
    RX_CAP = 4096

    def __init__(self, password, name, interval_us, dupterm_index, files=False, console=True, window=None, pairing=None):
        self.password = password
        #: None (password only), or the pairing mode in force.
        self.pairing = pairing
        self._security = None
        self.console = console
        self.files = None
        self.ft_flushing = False
        self.ft_in = bytearray()
        self.ft_scheduled = False
        self.ft_reset = False
        self.rx_handle = self.tx_handle = None
        self.ft_handle = self.auth_handle = None
        if files:
            from . import filetransfer

            self.files = filetransfer.FileServer(window=window or filetransfer.WINDOW)
        self.name = name
        self.interval_us = interval_us
        self.dupterm_index = dupterm_index
        self.running = False
        self.conn = None
        self.login = None
        self.authed = False
        self.mtu = 23
        self.rx = bytearray()
        self.rx_pos = 0
        self.tx = bytearray()
        self.flushing = False
        self.dropped_out = 0
        self.prev_term = None
        self.stream = _Stream(self)
        self.timer = None
        self.hang_up_at = None
        self.early_mtu = None

    # -- setup

    def start(self):
        import bluetooth
        import machine

        try:
            from aioble import core

            self.ble = core.ble
            core.ensure_active()
            _arm_aioble()
            if not getattr(core, "_bledev_repl_irq", False):
                core.register_irq_handler(_irq, None)
                core._bledev_repl_irq = True
            self._aioble = True
        except ImportError:
            self.ble = bluetooth.BLE()
            self.ble.active(True)
            self.ble.irq(_irq)
            self._aioble = False
        ble = self.ble
        try:
            ble.config(mtu=nus.MTU)
        except Exception:
            pass
        # With pairing, the stack itself refuses the protected characteristics
        # to a link that isn't encrypted (or, for a passkey, authenticated),
        # before anything here sees the request.
        if self.pairing is None:
            rd = wr = 0
        elif self.pairing == "justworks":
            rd, wr = _F_READ_ENC, _F_WRITE_ENC
        else:
            rd, wr = _F_READ_ENC | _F_READ_AUTHN, _F_WRITE_ENC | _F_WRITE_AUTHN
        services = []
        uuids = []
        if self.console:
            services.append(
                (
                    bluetooth.UUID(str(nus.SERVICE)),
                    (
                        (bluetooth.UUID(str(nus.TX)), 0x0010),  # notify
                        (bluetooth.UUID(str(nus.RX)), 0x0008 | 0x0004 | wr),  # write, write without response
                    ),
                )
            )
            uuids.append(nus.SERVICE)
        if self.files is not None:
            from . import filetransfer as ft

            services.append(
                (
                    bluetooth.UUID(ft.SERVICE.short),
                    (
                        (bluetooth.UUID(str(ft.VERSION)), 0x0002),  # read
                        # read, write without response, write, notify
                        (bluetooth.UUID(str(ft.TRANSFER)), 0x0002 | 0x0004 | 0x0008 | 0x0010 | rd | wr),
                        # read, write. Served even without a password, so the
                        # table is the same for every lock: hosts cache it.
                        (bluetooth.UUID(str(ft.AUTH)), 0x0002 | 0x0008 | rd | wr),
                    ),
                )
            )
            uuids.append(ft.SERVICE)
        handles = ble.gatts_register_services(tuple(services))
        if self.console:
            (self.tx_handle, self.rx_handle) = handles[0]
            # Appending: several writes between two IRQs arrive together.
            ble.gatts_set_buffer(self.rx_handle, 1024, True)
        if self.files is not None:
            (version, self.ft_handle, self.auth_handle) = handles[-1]
            ble.gatts_write(version, struct.pack("<I", ft.PROTOCOL_VERSION))
            # Room for a whole window of data, its header and the next
            # command: the board never offers more than this.
            ble.gatts_set_buffer(self.ft_handle, 2 * self.files.window + 64, True)
            ble.gatts_set_buffer(self.auth_handle, MAX_PASSWORD + 1)
            ble.gatts_write(self.auth_handle, b"\x00")
        self._forget_other_services()
        if self.pairing is not None:
            from . import security

            self._security = security.on_change(self.on_security)
        # One periodic timer for the life of the server, never re-armed: on
        # the esp32, re-initialising a virtual Timer while its alarm is being
        # dispatched calls a NULL handler and panics the board (seen as a
        # Guru Meditation in esp_timer's task during long prints).
        self.timer = machine.Timer(-1)
        self.timer.init(mode=machine.Timer.PERIODIC, period=_TICK_MS, callback=self._tick)
        self.adv = pack_advertisement(self.name, uuids)
        self.running = True
        self.advertise()

    def _forget_other_services(self):
        # The registration above replaced every service aioble and mpble knew,
        # so their handle tables now point at our handles. Clear them.
        mods = sys.modules
        server = mods.get("aioble.server")
        if server is not None:
            server._registered_characteristics.clear()
        mpble = mods.get("bledev.mpble")
        if mpble is not None:
            mpble._captures.clear()
            shared = getattr(mpble, "_shared", None)
            if shared is not None and hasattr(shared, "_nus_server"):
                del shared._nus_server

    def advertise(self):
        if self.running and self.conn is None:
            adv, resp = self.adv
            try:
                self.ble.gap_advertise(self.interval_us, adv_data=adv, resp_data=resp or None)
            except OSError:
                pass

    def stop(self):
        self.running = False
        if self._security is not None:
            from . import security

            security.remove_listener(self._security)
            self._security = None
        try:
            self.ble.gap_advertise(None)
        except Exception:
            pass
        if self.conn is not None:
            try:
                self.ble.gap_disconnect(self.conn)
            except Exception:
                pass
        self._detach()
        if self.timer is not None:
            self.timer.deinit()

    # -- connection events (from the BLE IRQ)

    def on_connect(self, conn):
        if self.conn is not None:
            self.ble.gap_disconnect(conn)  # one client at a time
            return
        self.conn = conn
        self.mtu = 23
        # MicroPython can report the MTU exchange before the connection.
        if self.early_mtu and self.early_mtu[0] == conn:
            self.mtu = self.early_mtu[1]
        self.early_mtu = None
        self.login = _Gate(self.password) if self.password is not None else _Open()
        self.hang_up_at = None
        self.authed = False
        self.rx = bytearray()
        self.rx_pos = 0
        self.tx = bytearray()
        if self.files is not None:
            self._ft_forget()
        if self.pairing is not None:
            # A bonded host may already be encrypting; on_security() takes over.
            import time

            from . import security

            self.hang_up_at = time.ticks_add(time.ticks_ms(), PAIR_WITHIN_MS)
            if self.secure(conn):
                self.on_security(conn, *security.state(conn))
            return
        if self.console:
            # Sent now in case the client is already listening; clients that
            # subscribe later ask for it again with an empty line.
            self.notify_now(PROMPT)

    # -- pairing

    def secure(self, conn):
        """Whether ``conn``'s link is as secure as this server asks."""
        if self.pairing is None:
            return True
        from . import security

        encrypted, authenticated, _bonded, _size = security.state(conn)
        if self.pairing == "justworks":
            return encrypted
        return encrypted and authenticated

    def on_security(self, conn, encrypted, authenticated, bonded, key_size):
        # From the BLE IRQ, when pairing or a bonded reconnect settles.
        if conn != self.conn:
            return
        if not self.secure(conn):
            # Failed pairing, a weaker one than asked for, or a host whose
            # keys this board no longer has. Stay connected so the host sees
            # its reads refused (and can say why); the pairing deadline set at
            # connect still hangs up on a host that never gets there.
            return
        self.hang_up_at = None  # the pairing deadline is met
        if self.password is None:
            # The pairing was the lock: the files open now, and the REPL on
            # the client's first line (_Open).
            if self.files is not None and not self.files.authed:
                self.files.authed = True
                self.ble.gatts_write(self.auth_handle, b"\x01")
        elif self.console and not self.authed:
            self.notify_now(PROMPT)

    def on_disconnect(self, conn):
        if conn != self.conn:
            return
        self._detach()
        self.conn = None
        if self.files is not None:
            self._ft_forget()
        self.hang_up_at = None
        self.login = None
        self.authed = False
        self.rx = bytearray()
        self.rx_pos = 0
        self.tx = bytearray()
        self.advertise()

    def on_write(self, conn, data):
        if conn != self.conn or not self.secure(conn):
            return
        if not self.authed:
            reply, verdict, rest = self.login.feed(data)
            if verdict is False:
                self.notify_now(reply)
                self.login.refused = True
                # Let "Access denied" reach the client, then hang up.
                import time

                self.hang_up_at = time.ticks_add(time.ticks_ms(), 300)
                return
            if verdict is None:
                if reply:
                    self.notify_now(reply)
                return
            self._attach()
            if self.files is not None:
                self.files.authed = True  # one password unlocks both
            self.send(reply)
            data = rest
            if not data:
                return
        self.feed_repl(data)

    def on_files(self, conn, data):
        # This runs in the BLE stack's task, whose stack is a few KB: too
        # small for filesystem work (a recursive delete crashed the board).
        # So the IRQ only queues the bytes, and the main thread does the rest.
        if conn != self.conn or not self.secure(conn):
            return
        self.ft_in.extend(data)
        if not self.ft_scheduled:
            self.ft_scheduled = True
            try:
                import micropython

                micropython.schedule(self._ft_work, None)
            except (ImportError, RuntimeError):
                self.ft_scheduled = False  # the queue is full; the tick picks it up

    def _ft_forget(self):
        # From the IRQ: lock the files and drop what's queued. Closing files
        # waits for the main thread, which may be in the middle of one.
        self.files.authed = False
        self.ft_in = bytearray()
        self.ft_reset = True
        self.ble.gatts_write(self.auth_handle, b"\x00")

    def _ft_work(self, _arg=None):
        self.ft_scheduled = False
        if self.ft_reset:
            self.ft_reset = False
            self.files.reset()
        if self.conn is None:
            return
        if self.ft_in:
            # Swap before feeding: bytes the IRQ adds meanwhile go to the new buffer.
            data = self.ft_in
            self.ft_in = bytearray()
            self.files.feed(data)
        self.ft_flush()

    def on_auth(self, conn, data):
        if conn != self.conn or self.files.authed or self.hang_up_at is not None or not self.secure(conn):
            return
        if self.password is None:
            return  # unlocked by pairing, not by a password
        given = bytes(data).rstrip(b"\r\n")
        want = self.password.encode() if isinstance(self.password, str) else bytes(self.password)
        if _check_password(given, want):
            self.files.authed = True
            self.ble.gatts_write(self.auth_handle, b"\x01")
            return
        # One attempt per connection, as for the REPL: refuse and hang up.
        if self.login is not None:
            self.login.refused = True
        import time

        self.hang_up_at = time.ticks_add(time.ticks_ms(), 300)

    def on_mtu(self, conn, mtu):
        if conn == self.conn:
            self.mtu = mtu
        else:
            self.early_mtu = (conn, mtu)

    # -- the REPL

    def _attach(self):
        import os

        self.authed = True
        self.prev_term = os.dupterm(self.stream, self.dupterm_index)

    def _detach(self):
        if not self.authed:
            return
        import os

        self.authed = False
        try:
            os.dupterm(self.prev_term, self.dupterm_index)
        except Exception:
            pass
        self.prev_term = None

    def feed_repl(self, data):
        if len(self.rx) - self.rx_pos + len(data) > self.RX_CAP:
            return
        self.rx.extend(data)
        if 3 in data:
            # Ctrl-C: have dupterm read it now, so a running program is
            # interrupted even though nothing is reading stdin.
            import os

            os.dupterm_notify(None)

    # -- sending

    def _tick(self, _timer=None):
        # Every _TICK_MS while the server runs, as a scheduled callback.
        if self.pairing is not None:
            from . import security

            security.poll()
        if self.hang_up_at is not None:
            import time

            if time.ticks_diff(time.ticks_ms(), self.hang_up_at) >= 0:
                self.hang_up_at = None
                self._hang_up()
        if self.tx and self.conn is not None:
            self.flush()
        if self.files is not None and (self.ft_reset or self.conn is not None and (self.ft_in or self.files.has_output())):
            self._ft_work()

    def _hang_up(self):
        if self.conn is None:
            return
        if self.pairing is not None and not self.secure(self.conn):
            try:
                self.ble.gap_disconnect(self.conn)
            except OSError:
                pass
            return
        if not self.authed and not (self.files is not None and self.files.authed):
            try:
                self.ble.gap_disconnect(self.conn)
            except OSError:
                pass

    def notify_now(self, data):
        """Send while unauthenticated (small replies); failures are ignored."""
        if self.conn is None:
            return
        size = self.mtu - 3
        for i in range(0, len(data), size):
            try:
                self.ble.gatts_notify(self.conn, self.tx_handle, data[i : i + size])
            except OSError:
                return

    def send(self, data):
        if self.conn is None or not self.authed:
            return
        self.tx.extend(data)
        self.flush()
        if len(self.tx) > self.TX_CAP:
            import time

            # A program printing faster than the link carries: wait for it,
            # but never forever, because print() can't fail.
            deadline = time.ticks_add(time.ticks_ms(), 2000)
            while len(self.tx) > self.TX_CAP and self.conn is not None:
                if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                    self.dropped_out += len(self.tx) - self.TX_CAP
                    self.tx = self.tx[: self.TX_CAP]
                    break
                time.sleep_ms(2)
                self.flush()

    def flush(self):
        # The timer's callback runs between the main program's
        # bytecodes, so it can land inside a flush() that print() started.
        # Two flushes interleaved sent one chunk twice and dropped the next,
        # so the second one leaves the work to the first.
        if self.flushing:
            return
        self.flushing = True
        try:
            size = self.mtu - 3
            while self.tx and self.conn is not None:
                chunk = self.tx[:size]
                try:
                    self.ble.gatts_notify(self.conn, self.tx_handle, chunk)
                except OSError:
                    return  # the controller's buffers are full; _tick retries
                self.tx = self.tx[len(chunk) :]
        finally:
            self.flushing = False


    def ft_flush(self):
        # File-transfer answers, one notification at a time; what the
        # controller can't take yet waits for the next tick. Main thread only,
        # but guarded like flush() against a tick landing inside it.
        if self.ft_flushing:
            return
        self.ft_flushing = True
        try:
            size = self.mtu - 3
            files = self.files
            while self.conn is not None:
                packet = files.packet(size)
                if packet is None:
                    return
                try:
                    self.ble.gatts_notify(self.conn, self.ft_handle, packet)
                except OSError:
                    return
                files.sent()
        finally:
            self.ft_flushing = False


class _Open:
    """The gate when pairing is the lock: the client's first line (the empty
    one every client sends to ask for a prompt) gets the banner and ``>>>``,
    and isn't passed to the REPL, so the client sees exactly one prompt."""

    refused = False
    verdict = None

    def feed(self, data):
        for i in range(len(data)):
            if data[i] in (10, 13):
                rest = bytes(data[i + 1 :])
                if data[i] == 13 and rest[:1] == b"\n":
                    rest = rest[1:]
                self.verdict = True
                return BANNER, True, rest
        return b"", None, b""


class _Gate(Login):
    refused = False

    def feed(self, data):
        if self.refused:
            return b"", False, b""
        return Login.feed(self, data)


def _irq(event, data):
    s = _server
    if s is None or not s.running:
        return None
    if event == 1:  # _IRQ_CENTRAL_CONNECT
        s.on_connect(data[0])
    elif event == 2:  # _IRQ_CENTRAL_DISCONNECT
        s.on_disconnect(data[0])
        _tidy_aioble(data[0])
    elif event == 3:  # _IRQ_GATTS_WRITE
        conn, handle = data
        if handle == s.rx_handle:
            s.on_write(conn, bytes(s.ble.gatts_read(handle)))
        elif handle == s.ft_handle:
            s.on_files(conn, bytes(s.ble.gatts_read(handle)))
        elif handle == s.auth_handle:
            s.on_auth(conn, bytes(s.ble.gatts_read(handle)))
    elif event == 21:  # _IRQ_MTU_EXCHANGED
        s.on_mtu(data[0], data[1])
    return None


def _arm_aioble():
    # aioble's peripheral IRQ signals its advertise() on every incoming
    # connection and raises if advertise() never ran, which would stop the
    # IRQ reaching us. Give it something to signal.
    try:
        import asyncio
        from aioble import peripheral
    except ImportError:
        return
    if peripheral._connect_event is None:
        peripheral._connect_event = asyncio.ThreadSafeFlag()


def _tidy_aioble(conn):
    # aioble's peripheral IRQ records every incoming connection, expecting its
    # own advertise() to start a task that forgets it on disconnect. Ours
    # never went through advertise(), so forget it here.
    try:
        from aioble import peripheral
        from aioble.device import DeviceConnection
    except ImportError:
        return
    connection = DeviceConnection._connected.pop(conn, None)
    if connection is not None:
        connection._conn_handle = None
        connection.device._connection = None
    if peripheral._incoming_connection is connection:
        peripheral._incoming_connection = None
        if peripheral._connect_event is not None:
            try:
                peripheral._connect_event.clear()
            except AttributeError:
                pass


# ---------------------------------------------------------------- the client side


async def _expect(link, markers, buffer, timeout_ms):
    """Read until one of ``markers`` appears; return (marker, everything read)."""
    while True:
        for marker in markers:
            if marker in buffer:
                return marker, buffer
        chunk = await wait_ms(link.read(), timeout_ms, "waiting for {!r}".format(markers[0]))
        if not chunk:
            return None, buffer
        buffer.extend(chunk)


def refused(pair, passkey):
    """The :class:`bledev.PairingError` for a board that refused a link."""
    if not pair:
        return PairingError("the board wants pairing: connect with pair=True")
    if passkey is None:
        return PairingError("the board wants a link paired with a passkey (pass passkey=), or " + STALE_BOND)
    return PairingError(STALE_BOND)


async def connect(ble, password=None, name="mpy-repl", *, device=None, timeout_ms=10000, pair=False, passkey=None, **connect_options):
    """Log in to a board's BLE REPL and return the :class:`bledev.nus.Link`, at ``>>>``.

    ``pair=True`` pairs first (bonding, so the next connect skips it), for a
    board started with ``pairing=``; ``passkey`` is what its display shows,
    or a callable that asks for it. A board that pairing unlocks alone needs
    no ``password``.

    Raises :class:`AuthError` if the board refuses the password, and
    :class:`bledev.PairingError` if pairing fails or the board refuses the
    keys this host kept.
    """
    try:
        link = await nus.connect(ble, name=name, device=device, timeout_ms=timeout_ms, pair=pair, passkey=passkey, **connect_options)
    except GattError as e:
        if e.status in NEEDS_PAIRING:
            raise refused(pair, passkey)
        raise
    try:
        buffer = bytearray()
        try:
            await link.write(b"\r")
        except GattError as e:
            if e.status not in NEEDS_PAIRING:
                raise
            raise refused(pair, passkey)
        marker, buffer = await _expect(link, (PROMPT, b">>> "), buffer, timeout_ms)
        if marker is None:
            raise BLEError("the board closed the link before asking for a password")
        if marker == PROMPT:
            if password is None:
                raise AuthError("the board wants a password")
            del buffer[: buffer.find(PROMPT) + len(PROMPT)]
            secret = password.encode() if isinstance(password, str) else bytes(password)
            await link.write(secret + b"\r")
            marker, buffer = await _expect(link, (b">>> ", DENIED.strip()), buffer, timeout_ms)
            if marker != b">>> ":
                raise AuthError("the board refused the password")
    except BaseException:
        await link.close()
        raise
    return link


async def run(link, code, timeout_ms=10000):
    """Type ``code`` at the prompt and return what it printed, up to the next ``>>>``."""
    line = code.encode() if isinstance(code, str) else bytes(code)
    await link.write(line + b"\r")
    marker, buffer = await _expect(link, (b">>> ",), bytearray(), timeout_ms)
    if marker is None:
        raise BLEError("the link closed while running {!r}".format(code))
    text = bytes(buffer[: buffer.rfind(b">>> ")]).decode("utf-8", "replace")
    # Drop the echoed command.
    first = text.find("\n")
    return text[first + 1 :] if first >= 0 else ""
