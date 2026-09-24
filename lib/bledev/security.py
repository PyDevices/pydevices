"""Pairing and bonding on a MicroPython board: the bond store, passkeys, link state.

You rarely call this yourself. ``bledev.repl.start(pairing=...)`` and
``bledev.filetransfer.start(pairing=...)`` set it up, and a central's
``connection.pair()`` uses it. What it adds to aioble:

* **A bond store that survives a filesystem erase.** On an ESP32 the keys go
  in NVS (namespace ``bledev``), which a reformat of the filesystem, a
  ``mip`` reinstall or deleting every file leaves alone. A full chip erase
  (``esptool erase_flash``, ``mpftp firmware flash --erase``) loses them, and
  so does :func:`forget`. Elsewhere they go in aioble's ``ble_secrets.json``.
* **Passkeys.** aioble leaves the passkey step unhandled. Here a board with a
  display shows a random six-digit passkey (``io=DISPLAY_ONLY``) for the host
  to type in; numeric comparison shows a number both sides must confirm; and
  a board as central types in the passkey its peer shows.
* **Link state per connection**, from the stack's encryption updates:
  :func:`state` and :func:`on_change` tell a server whether a link is
  encrypted, authenticated (passkey or numeric comparison) and bonded.

Only the board side lives here. A laptop's pairing is the OS's, through
``bledev.bleak``.
"""

import os
import sys

try:
    from micropython import const
except ImportError:  # CPython, for the store's tests

    def const(x):
        return x


_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_ENCRYPTION_UPDATE = const(28)
_IRQ_GET_SECRET = const(29)
_IRQ_SET_SECRET = const(30)
_IRQ_PASSKEY_ACTION = const(31)

#: IO capabilities, as ``ble.config(io=...)`` takes them.
IO_DISPLAY_ONLY = 0
IO_DISPLAY_YESNO = 1
IO_KEYBOARD_ONLY = 2
IO_NO_INPUT_OUTPUT = 3
IO_KEYBOARD_DISPLAY = 4

_ACTION_INPUT = const(2)
_ACTION_DISPLAY = const(3)
_ACTION_NUMCMP = const(4)

#: The pairing modes a server takes. ``"auto"`` is ``"passkey"`` on a board
#: with a display and ``"justworks"`` without one.
MODES = ("justworks", "passkey", "numeric", "auto")

# conn_handle -> (encrypted, authenticated, bonded, key_size)
_links = {}
_listeners = []
# conn_handle -> what to type in when this board, as central, is asked for the
# peer's passkey: an int, or a callable returning one.
_inputs = {}
# The server's side: what to do when the stack wants a passkey shown or a
# number confirmed. Set by configure().
_show = None
_hide = None
_confirm = None
_installed = False
_store = None


# ---------------------------------------------------------------- the bond store


class FileStore:
    """aioble's ``ble_secrets.json``, the format bledev.hid used first."""

    kind = "file"

    def __init__(self, path="ble_secrets.json"):
        self.path = path

    def load(self):
        import binascii
        import json

        secrets = {}
        try:
            with open(self.path) as f:
                for sec_type, key, value in json.load(f):
                    secrets[sec_type, binascii.a2b_base64(key)] = binascii.a2b_base64(value)
        except (OSError, ValueError):
            pass
        return secrets

    def save(self, secrets):
        import binascii
        import json

        entries = [
            (t, binascii.b2a_base64(k).decode().strip(), binascii.b2a_base64(v).decode().strip())
            for (t, k), v in secrets.items()
        ]
        with open(self.path, "w") as f:
            json.dump(entries, f)

    def erase(self):
        try:
            os.remove(self.path)
        except OSError:
            pass


class NVSStore:
    """The keys in ESP32 NVS, outside the filesystem.

    One blob, ``bonds``, in namespace ``bledev``: for each secret its type
    (1 byte), key length (1), key, value length (2, little-endian), value.
    """

    kind = "nvs"
    _KEY = "bonds"
    _LEN = "bonds_len"

    def __init__(self, namespace="bledev"):
        import esp32

        self._nvs = esp32.NVS(namespace)

    def load(self):
        secrets = {}
        try:
            n = self._nvs.get_i32(self._LEN)
        except OSError:
            return secrets
        if n <= 0:
            return secrets
        buf = bytearray(n)
        try:
            self._nvs.get_blob(self._KEY, buf)
        except OSError:
            return secrets
        return unpack_secrets(buf)

    def save(self, secrets):
        out = pack_secrets(secrets)
        if out:
            self._nvs.set_blob(self._KEY, out)
        self._nvs.set_i32(self._LEN, len(out))
        self._nvs.commit()

    def erase(self):
        for key in (self._KEY, self._LEN):
            try:
                self._nvs.erase_key(key)
            except OSError:
                pass
        self._nvs.commit()


def pack_secrets(secrets):
    """The NVS blob for ``{(type, key): value}``."""
    out = bytearray()
    for (t, key), value in secrets.items():
        out.append(t)
        out.append(len(key))
        out.extend(key)
        out.append(len(value) & 0xFF)
        out.append(len(value) >> 8)
        out.extend(value)
    return out


def unpack_secrets(buf):
    """``{(type, key): value}`` from an NVS blob; a torn tail is dropped."""
    secrets = {}
    n = len(buf)
    i = 0
    while i + 2 <= n:
        t = buf[i]
        kl = buf[i + 1]
        if i + 2 + kl + 2 > n:
            break
        key = bytes(buf[i + 2 : i + 2 + kl])
        i += 2 + kl
        vl = buf[i] | (buf[i + 1] << 8)
        if i + 2 + vl > n:
            break
        secrets[t, key] = bytes(buf[i + 2 : i + 2 + vl])
        i += 2 + vl
    return secrets


def default_store():
    """NVS on an ESP32, the file anywhere else."""
    try:
        return NVSStore()
    except (ImportError, OSError):
        return FileStore()


def use_store(store=None):
    """Keep the keys in ``store`` (a :class:`NVSStore`, a :class:`FileStore`, or
    ``"nvs"``/``"file"``; default :func:`default_store`) and turn bonding on.

    Safe to call again; the last store wins. Returns the store.
    """
    global _store
    if store is None:
        store = default_store()
    elif store == "nvs":
        store = NVSStore()
    elif store == "file":
        store = FileStore()
    elif isinstance(store, str):
        store = FileStore(store)
    _store = store
    _install()
    from aioble import security as sec

    # aioble keeps the secrets in one dict and schedules _save_secrets when
    # the stack changes one; core.ensure_active() calls load_secrets before
    # the radio starts. Both are looked up at call time, so these take over.
    sec._secrets = store.load()
    sec._modified = False
    sec._save_secrets = _save
    sec.load_secrets = _load
    return store


def store():
    """The store in use, or ``None`` before :func:`use_store`."""
    return _store


def _load(path=None):
    from aioble import security as sec

    if _store is not None:
        sec._secrets = _store.load()


def _save(_arg=None):
    global _save_pending
    from aioble import security as sec

    _save_pending = False
    sec._modified = False
    (_store or default_store()).save(sec._secrets)


def bonds():
    """How many peers this board holds keys for."""
    from aioble import security as sec

    # Each bond stores the peer's keys (type 2) and ours (type 1).
    return sum(1 for (t, _k) in sec._secrets if t == 2)


def forget(address=None):
    """Forget every bond, or the ones with ``address`` (6 bytes, or
    ``"aa:bb:cc:dd:ee:ff"``). A host that still holds its half must then be
    unpaired on the host before it can pair again."""
    from aioble import security as sec

    if address is None:
        sec._secrets = {}
        if _store is not None:
            _store.erase()
        return
    if isinstance(address, str):
        import binascii

        address = binascii.unhexlify(address.replace(":", ""))
    address = bytes(address)
    backwards = bytes(reversed(address))
    for key in list(sec._secrets):
        raw = key[1]
        if address in raw or backwards in raw:
            del sec._secrets[key]
    _save()


# ---------------------------------------------------------------- link state


def state(conn_handle):
    """``(encrypted, authenticated, bonded, key_size)`` for a connection."""
    return _links.get(conn_handle, (False, False, False, 0))


def on_change(callback):
    """Call ``callback(conn_handle, encrypted, authenticated, bonded, key_size)``
    from the BLE IRQ whenever a link's security changes. Returns ``callback``."""
    if callback not in _listeners:
        _listeners.append(callback)
    return callback


def remove_listener(callback):
    if callback in _listeners:
        _listeners.remove(callback)


def expect_passkey(conn_handle, passkey):
    """As central: the passkey to type in when this connection's peer shows one
    (an int, a string of digits, or a callable returning either)."""
    if passkey is None:
        _inputs.pop(conn_handle, None)
    else:
        _inputs[conn_handle] = passkey


def configure(mode, *, show=None, hide=None, confirm=None, display=None):
    """Set this board's pairing as a peripheral. Returns the mode actually used.

    ``mode`` is one of :data:`MODES`. ``show(passkey)`` is called with the
    six-digit number to display (passkey and numeric), and ``hide()`` once the
    link's security settles; without ``show``, the number goes on
    ``display`` (default: ``board_config.display_drv`` when the board has one)
    and to the console. ``confirm(number)`` answers numeric comparison with
    True or False, or returns ``None`` and calls :func:`answer` later.
    """
    global _show, _hide, _confirm
    if mode not in MODES:
        raise ValueError("pairing must be one of {}".format(", ".join(MODES)))
    if mode == "auto" or (mode in ("passkey", "numeric") and show is None):
        if display is None:
            display = find_display()
    if mode == "auto":
        mode = "passkey" if (display is not None or show is not None) else "justworks"
    if mode == "numeric" and confirm is None:
        raise ValueError("numeric comparison needs confirm=")
    if show is None and mode in ("passkey", "numeric"):
        show, hide = display_passkey(display)
    _show = show
    _hide = hide
    _confirm = confirm
    _install()
    import aioble

    io = {"justworks": IO_NO_INPUT_OUTPUT, "passkey": IO_DISPLAY_ONLY, "numeric": IO_DISPLAY_YESNO}[mode]
    aioble.config(bond=True, le_secure=True, mitm=mode != "justworks", io=io)
    return mode


def answer(conn_handle, accept):
    """Answer a numeric comparison that ``confirm`` deferred."""
    from aioble import core

    core.ble.gap_passkey(conn_handle, _ACTION_NUMCMP, 1 if accept else 0)


def random_passkey():
    """Six random digits, as an int (000000-999999)."""
    b = os.urandom(4)
    return ((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]) % 1000000


def _install():
    global _installed
    if _installed:
        return
    from aioble import core
    from aioble import security  # noqa: F401  registers aioble's secret handlers

    # Ahead of aioble's: its secret handler saves through micropython.schedule
    # and raises when the queue is full, which fails the stack's key store in
    # the middle of pairing. The queue is full whenever a scheduled callback
    # runs long (drawing the passkey is one) while a timer keeps queueing.
    core._irq_handlers.insert(0, _secret_irq)
    core.register_irq_handler(_irq, None)
    _installed = True


def _secret_irq(event, data):
    if event == _IRQ_SET_SECRET:
        from aioble import security as sec

        sec_type, key, value = data
        key = sec_type, bytes(key)
        if value is None:
            if key not in sec._secrets:
                return False
            del sec._secrets[key]
        else:
            sec._secrets[key] = bytes(value)
        _save_soon()
        return True
    if event == _IRQ_GET_SECRET:
        from aioble import security as sec

        sec_type, index, key = data
        if key is None:
            i = 0
            for (t, _k), value in sec._secrets.items():
                if t == sec_type:
                    if i == index:
                        return value
                    i += 1
            return None
        return sec._secrets.get((sec_type, bytes(key)), None)
    return None


_save_pending = False


def _save_soon():
    global _save_pending
    if _save_pending:
        return
    _save_pending = True
    import micropython

    try:
        micropython.schedule(_save, None)
    except RuntimeError:
        _save()  # the queue is full: write now, from the stack's task


def _irq(event, data):
    if event == _IRQ_ENCRYPTION_UPDATE:
        conn, encrypted, authenticated, bonded, key_size = data
        _links[conn] = (bool(encrypted), bool(authenticated), bool(bonded), key_size)
        if _hide is not None:
            _defer(_call_hide, None)
        for callback in _listeners:
            callback(conn, bool(encrypted), bool(authenticated), bool(bonded), key_size)
    elif event == _IRQ_PASSKEY_ACTION:
        conn, action, number = data
        from aioble import core

        if action == _ACTION_DISPLAY:
            # Answer the stack at once, from here, as NimBLE's own examples
            # do; only the drawing waits for the main thread.
            passkey = random_passkey()
            core.ble.gap_passkey(conn, action, passkey)
            if _show is not None:
                _defer(_show, passkey)
        elif action == _ACTION_INPUT and not callable(_inputs.get(conn)):
            given = _inputs.get(conn)
            # No passkey to give: answer with one that can't be relied on to
            # match, so the pairing fails now rather than at a timeout.
            core.ble.gap_passkey(conn, action, int(given) if given is not None else random_passkey())
        else:
            # Numeric comparison, or a passkey someone has to be asked for.
            _defer(_passkey_action, (conn, action, number))
        return True
    elif event in (_IRQ_CENTRAL_DISCONNECT, _IRQ_PERIPHERAL_DISCONNECT):
        conn = data[0]
        had = _links.pop(conn, None)
        _inputs.pop(conn, None)
        if had is None and _hide is not None:
            _defer(_call_hide, None)
    return None


_deferred = []


def _defer(fn, arg):
    """Run ``fn(arg)`` on the main thread soon. If the scheduler's queue is
    full, :func:`poll` (which bledev.repl's server calls every tick) runs it."""
    import micropython

    try:
        micropython.schedule(fn, arg)
    except RuntimeError:
        _deferred.append((fn, arg))


def poll():
    """Run work the IRQ couldn't schedule. Cheap when there's none."""
    while _deferred:
        fn, arg = _deferred.pop(0)
        try:
            fn(arg)
        except Exception as e:
            sys.print_exception(e)


def _call_hide(_arg=None):
    if _hide is not None:
        try:
            _hide()
        except Exception as e:
            sys.print_exception(e)


def _passkey_action(args):
    from aioble import core

    conn, action, number = args
    ble = core.ble
    try:
        if action == _ACTION_NUMCMP:
            if _show is not None:
                _show(number)
            verdict = _confirm(number) if _confirm is not None else False
            if verdict is not None:
                ble.gap_passkey(conn, action, 1 if verdict else 0)
        elif action == _ACTION_INPUT:
            given = _inputs.get(conn)
            if callable(given):
                given = given()
            # No passkey to give: answer with one that can't match, so the
            # pairing fails now rather than when the host times out.
            ble.gap_passkey(conn, action, int(given) if given is not None else random_passkey())
    except Exception as e:
        sys.print_exception(e)


# ---------------------------------------------------------------- the display


def find_display():
    """``board_config.display_drv``, or ``None`` on a board without a display."""
    try:
        import board_config
    except Exception:
        return None
    return getattr(board_config, "display_drv", None)


def display_passkey(display=None):
    """``(show, hide)``: draw a passkey big in the middle of ``display``, and
    clear it again. Also prints it to the console. Without a display, only
    prints."""

    box = []

    def show(passkey):
        text = "{:06d}".format(passkey)
        print("bledev: Bluetooth passkey", text[:3], text[3:])
        if display is not None:
            try:
                box[:] = [_draw(display, text[:3] + " " + text[3:])]
            except Exception as e:
                sys.print_exception(e)

    def hide():
        if display is not None and box:
            x, y, w, h = box.pop()
            try:
                display.fill_rect(x, y, w, h, 0)
                _refresh(display)
            except Exception as e:
                sys.print_exception(e)

    return show, hide


def _refresh(display):
    show = getattr(display, "show", None)
    if show is not None:
        show()


def _draw(display, digits, title="Bluetooth passkey"):
    import framebuf

    w = display.width
    h = display.height
    # The digits as big as fit in 90 % of the width, at most 8x the 8-pixel font.
    big = max(1, min(8, (w * 9 // 10) // (len(digits) * 8)))
    small = max(1, big * 3 // 8)
    bw = max(len(digits) * 8 * big, len(title) * 8 * small) + 4 * big
    bh = 8 * small + 8 * big + 6 * big
    x = (w - bw) // 2
    y = (h - bh) // 2
    display.fill_rect(x, y, bw, bh, 0)
    white = 0xFFFF
    _text(display, framebuf, title, (w - len(title) * 8 * small) // 2, y + 2 * big, small, white)
    _text(display, framebuf, digits, (w - len(digits) * 8 * big) // 2, y + 8 * small + 4 * big, big, white)
    _refresh(display)
    return x, y, bw, bh


def _text(display, framebuf, text, x0, y0, scale, color):
    n = len(text) * 8
    buf = bytearray(n)  # MONO_HLSB, 8 rows of n pixels
    fb = framebuf.FrameBuffer(buf, n, 8, framebuf.MONO_HLSB)
    fb.text(text, 0, 0, 1)
    for row in range(8):
        col = 0
        while col < n:
            if fb.pixel(col, row):
                start = col
                while col < n and fb.pixel(col, row):
                    col += 1
                display.fill_rect(x0 + start * scale, y0 + row * scale, (col - start) * scale, scale, color)
            else:
                col += 1
