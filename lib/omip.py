# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Install an OmniPython package with one line, and everything it needs.

    import omip
    omip.install("bledev")
    omip.search("display")

That gets the board online if it isn't, looks for the package on the OmniPython
index and then on micropython-lib, and brings what it needs from both. It takes
the arguments of `mip.install`, and works on MicroPython, CircuitPython and
desktop Python. To get this one file onto a stock MicroPython board:

    import mip
    mip.install("github:PyDevices/pydevices/lib/omip.py")

A package names what it needs from micropython-lib under `upstream` in its JSON,
beside `deps`. `mip` and `mpremote` ignore that key, so they behave as they
always have: `mip` takes every file of a package from the one index it was given.
"""

import gc
import json
import os
import sys
import time

INDEX = "https://lib.omnipython.org"
UPSTREAM = "https://micropython.org/pi/v2"

_MP = sys.implementation.name == "micropython"
_CP = sys.implementation.name == "circuitpython"
_URL_PREFIXES = ("http://", "https://", "codeberg:", "github:", "gitlab:")
_HOSTS = {
    "codeberg:": "codeberg.org/api/v1/repos/{}/{}/raw/{p}?ref={}",
    "github:": "raw.githubusercontent.com/{}/{}/{}/{p}",
    "gitlab:": "gitlab.com/{}/{}/-/raw/{}/{p}",
}
_READ_ONLY = (
    "%s is read-only, usually because a computer has the CIRCUITPY drive mounted. Either put "
    'import storage; storage.remount("/", False) in boot.py and restart (the '
    "computer can't write to the drive then), or install from the computer with "
    "circup or mcuctl."
)


# Getting a URL. Each returns the HTTP status and hands the body to write().

if _MP:

    def _get(url, write):
        try:
            import requests
        except ImportError:
            raise OSError("This firmware has no network libraries: install from a computer with mcuctl")
        response = requests.get(url)
        try:
            if response.status_code == 200:
                # In pieces, so an index larger than the free heap can still be searched.
                while True:
                    chunk = response.raw.read(512)
                    if not chunk:
                        break
                    write(chunk)
            return response.status_code
        finally:
            response.close()

elif _CP:

    _pool = None

    def _header(head, name):
        for line in head.split(b"\r\n")[1:]:
            key, _, value = line.partition(b":")
            if key.strip().lower() == name:
                return value.strip().decode()
        return None

    def _get(url, write, hops=4):
        # CircuitPython's core has sockets and TLS but no HTTP client, and a
        # single file can't lean on adafruit_requests.
        global _pool
        try:
            import socketpool
            import ssl
            import wifi
        except ImportError:
            raise OSError("This board has no Wi-Fi: install from a computer with circup or mcuctl")
        if _pool is None:
            _pool = socketpool.SocketPool(wifi.radio)
        scheme, _, rest = url.partition("://")
        netloc, _, path = rest.partition("/")
        host, _, port = netloc.partition(":")
        port = int(port) if port else (443 if scheme == "https" else 80)
        sock = _pool.socket(_pool.AF_INET, _pool.SOCK_STREAM)
        try:
            sock.settimeout(30)
            if scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            sock.connect((host, port))
            # HTTP/1.0, so the body can't come chunked.
            sock.send(("GET /%s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n" % (path, netloc)).encode())
            buf = bytearray(512)
            view = memoryview(buf)
            head = b""
            while b"\r\n\r\n" not in head:
                n = sock.recv_into(buf)
                if not n:
                    raise OSError("connection closed in the HTTP headers")
                head += bytes(view[:n])
            head, body = head.split(b"\r\n\r\n", 1)
            status = int(head.split(b" ", 2)[1])
            location = _header(head, b"location")
            if status in (301, 302, 303, 307, 308) and location and hops:
                sock.close()
                if not location.startswith("http"):
                    location = "%s://%s%s" % (scheme, netloc, location)
                return _get(location, write, hops - 1)
            if status != 200:
                return status
            length = _header(head, b"content-length")
            left = int(length) if length else -1  # -1: read until the server closes
            while left:
                if not body:
                    n = sock.recv_into(buf)
                    if not n:
                        break
                    body = bytes(view[:n])
                write(body)
                left -= len(body)
                body = b""
            if left > 0:
                raise OSError("connection closed with %d bytes to come" % left)
            return status
        finally:
            sock.close()

else:

    def _get(url, write):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        try:
            # Some hosts refuse urllib's own user agent.
            with urlopen(Request(url, headers={"User-Agent": "omip"}), timeout=30) as response:
                while True:
                    chunk = response.read(4096)
                    if not chunk:
                        return response.status
                    write(chunk)
        except HTTPError as exc:
            return exc.code


def _request(url, write):
    """`_get`, with a failed connection's error naming the URL it was getting."""
    try:
        return _get(url, write)
    except OSError as exc:
        raise OSError("Couldn't get %s: %s" % (url, exc))


def _read_json(url):
    """The JSON at url, or None when it isn't there."""
    parts = []
    status = _request(url, parts.append)
    if status == 404:
        return None
    if status != 200:
        raise OSError("HTTP %d from %s" % (status, url))
    return json.loads(b"".join(parts))


def _is_url(spec):
    return any(spec.startswith(prefix) for prefix in _URL_PREFIXES)


def _rewrite_url(url, version):
    for host, form in _HOSTS.items():
        if url.startswith(host):
            parts = url[len(host) :].split("/")
            return "https://" + form.format(parts[0], parts[1], version or "HEAD", p="/".join(parts[2:]))
    return url


class _Plan:
    """What a walk found: which installs to ask for, and every file they should land."""

    def __init__(self, channel):
        self.channel = channel
        self.seen = []
        self.roots = []  # [spec, index, version]: one mip.install each on MicroPython
        self.files = []  # (target path, index or URL, short hash or None)


def _walk(plan, spec, version, indexes, root=False):
    """Read spec's JSON and everything it needs into plan. Returns the index it was found on."""
    if spec in plan.seen:
        return None
    plan.seen.append(spec)
    entry = [spec, indexes[0], version]
    if root:
        plan.roots.append(entry)
    base = None
    if _is_url(spec):
        url = _rewrite_url(spec, version)
        if spec.endswith(".py") or spec.endswith(".mpy"):
            plan.files.append((spec.rsplit("/", 1)[-1], url, None))
            return indexes[0]
        if not spec.endswith(".json"):
            url = url.rstrip("/") + "/package.json"
        body = _read_json(url)
        if body is None:
            raise OSError("Package not found: %s" % url)
        base = url.rpartition("/")[0]
    else:
        for index in indexes:
            body = _read_json("%s/package/%s/%s/%s.json" % (index, plan.channel, spec, version or "latest"))
            if body is not None:
                entry[1] = index
                break
        else:
            raise OSError("Package not found: %s (looked on %s)" % (spec, ", ".join(indexes)))
        indexes = [entry[1]]
    for path, short in body.get("hashes", ()):
        plan.files.append((path, entry[1], short))
    for path, url in body.get("urls", ()):
        if base and not _is_url(url):
            url = "%s/%s" % (base, url)
        plan.files.append((path, _rewrite_url(url, version), None))
    first = True
    for dep, dep_version in body.get("deps", ()):
        found = _walk(plan, dep, dep_version, indexes)
        # mip looks up all of a package.json's named deps on the one index it is given.
        if base and first and found and not _is_url(dep):
            entry[1] = found
            first = False
    for dep, dep_version in body.get("upstream", ()):
        # micropython-lib is for MicroPython: CircuitPython's own libraries
        # come from Adafruit's bundle, so only a URL means anything there.
        if _CP and not _is_url(dep):
            print("Skipping %s: it's for MicroPython. CircuitPython libraries come from circup." % dep)
        else:
            _walk(plan, dep, dep_version, [UPSTREAM], root=True)
    return entry[1]


def _ensure_parent(path):
    parts = path.split("/")
    prefix = parts[0]
    for part in parts[1:]:
        if prefix:
            try:
                os.stat(prefix)
            except OSError:
                os.mkdir(prefix)
        prefix += "/" + part


def _matches(path, short):
    """Whether the file at path already has this short hash."""
    try:
        import binascii
        import hashlib

        digest = hashlib.sha256() if hasattr(hashlib, "sha256") else hashlib.new("sha256")
        with open(path, "rb") as f:
            while True:
                chunk = f.read(512)
                if not chunk:
                    break
                digest.update(chunk)
        return binascii.hexlify(digest.digest()).decode()[: len(short)] == short
    except (ImportError, OSError):
        return False


def _fetch(path, source, short, target):
    """Download one file into target, unless it is already there."""
    dest = target + "/" + path
    if short and _matches(dest, short):
        print("Exists:", dest)
        return
    url = source if short is None else "%s/file/%s/%s" % (source, short[:2], short)
    print("Copying:", dest)
    _ensure_parent(dest)
    try:
        with open(dest, "wb") as f:
            status = _request(url, f.write)
    except OSError:
        # A partial file would pass for the real one where there's no hash to check.
        os.remove(dest)
        raise
    if status != 200:
        os.remove(dest)
        raise OSError("HTTP %d from %s" % (status, url))


def _default_target():
    for path in sys.path:
        if not path.startswith("/rom") and path.endswith("/lib"):
            return path
    return "lib"


def _check_writable(target):
    """Say what to do about a read-only filesystem before anything is fetched."""
    probe = target + "/.omip"
    try:
        _ensure_parent(probe)
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
    except OSError as exc:
        raise OSError(_READ_ONLY % target if _CP else "Can't write to %s: %s" % (target, exc))


# Getting online.


def _radio():
    """The Wi-Fi station to bring up, or None where there is none to manage."""
    try:
        if _CP:
            import wifi

            return wifi.radio
        if _MP:
            import network

            return network.WLAN(network.STA_IF)
    except (ImportError, AttributeError):
        pass
    return None


def _join(radio, ssid, password, timeout):
    print("Connecting to", ssid)
    try:
        if _CP:
            radio.connect(ssid, password, timeout=timeout)
            return True
        radio.active(True)
        try:
            radio.disconnect()
        except OSError:
            pass
        radio.connect(ssid, password)
        start = time.time()
        while time.time() - start < timeout:
            if radio.isconnected():
                return True
            time.sleep(0.25)
        radio.disconnect()
        print("%s didn't answer in %d seconds" % (ssid, timeout))
    except OSError as exc:
        print("%s: %s" % (ssid, exc))
    return False


def _from_secrets():
    """The (ssid, password) in a secrets module, in any of the usual shapes."""
    try:
        module = __import__("secrets")
    except ImportError:
        return None, None
    table = getattr(module, "secrets", {})
    ssid = getattr(module, "WIFI_SSID", None) or getattr(module, "ssid", None) or table.get("ssid")
    password = getattr(module, "WIFI_PASSWORD", None) or getattr(module, "password", None) or table.get("password")
    return ssid, password


def _from_settings():
    """The (ssid, password) in settings.toml, CircuitPython's usual place for them."""
    if _CP:
        return os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD")
    return None, None


def _save(ssid, password):
    """Keep a typed password, only because its owner just said to."""
    try:
        if _CP:
            quoted = [s.replace("\\", "\\\\").replace('"', '\\"') for s in (ssid, password)]
            with open("settings.toml", "a") as f:
                f.write('CIRCUITPY_WIFI_SSID = "%s"\nCIRCUITPY_WIFI_PASSWORD = "%s"\n' % tuple(quoted))
        else:
            with open("secrets.py", "a") as f:
                f.write("WIFI_SSID = %r\nWIFI_PASSWORD = %r\n" % (ssid, password))
    except OSError as exc:
        print("Couldn't save them:", exc)


def _ask(radio, timeout):
    """Ask at the REPL. Enter on its own skips Wi-Fi, for a board that's online some other way."""
    try:
        if _CP:
            import supervisor

            if not supervisor.runtime.serial_connected:
                return False
        ssid = input("Wi-Fi network (Enter to skip): ").strip()
        if not ssid:
            return False
        password = input("Password: ")
        if not _join(radio, ssid, password, timeout):
            return False
        if input("Save them on this board for next time? [y/N] ").strip().lower() == "y":
            _save(ssid, password)
        return True
    except (EOFError, ImportError):
        return False


def connect(prompt=True, timeout=30):
    """Get the board online, if it isn't already.

    Already connected, it does nothing. Otherwise it uses a `secrets` module or
    `settings.toml`, and failing those asks at the REPL. A typed password is only
    saved if you say so.

    Args:
        prompt (bool): Whether it may ask. A program with no one at the REPL
            passes `False`, because `input()` would wait forever on MicroPython.
        timeout (int): Seconds to wait for each network to answer.

    Returns:
        bool: Whether the board is online, as far as Wi-Fi can tell.
    """
    radio = _radio()
    if radio is None:
        return True
    if radio.ipv4_address if _CP else radio.isconnected():
        return True
    for ssid, password in (_from_secrets(), _from_settings()):
        if ssid and _join(radio, ssid, password or "", timeout):
            return True
    return bool(prompt and _ask(radio, timeout))


def _each_package(found):
    """A `write` for `_get` that hands found() each package of an index.json, one at a time."""
    depth = 0
    quoted = escaped = False
    package = bytearray()

    def write(chunk):
        nonlocal depth, quoted, escaped, package
        for byte in chunk:
            if depth:
                package.append(byte)
            if quoted:
                if escaped:
                    escaped = False
                elif byte == 92:  # backslash
                    escaped = True
                elif byte == 34:  # double quote
                    quoted = False
            elif byte == 34:
                quoted = True
            elif byte == 123:  # {
                depth += 1
                if depth == 2:
                    package = bytearray(b"{")
            elif byte == 125:  # }
                depth -= 1
                if depth == 1:
                    found(json.loads(package))
                    package = bytearray()

    return write


def search(*words, index=None, prompt=True):
    """Print the packages whose name or description has every one of the words.

    With no words, it prints every package. It reads the index a piece at a time,
    so it needs little memory, but on a board it takes as long as the download.

    Args:
        words (str): What to look for, in any case.
        index (str): The index to search. By default the OmniPython index, then
            micropython-lib.
        prompt (bool): Whether `connect` may ask for Wi-Fi details.

    Raises:
        OSError: An index couldn't be read.
    """
    connect(prompt)
    words = [word.lower() for word in words]

    def found(package):
        name, description = package["name"], package.get("description", "")
        text = (name + " " + description).lower()
        for word in words:
            if word not in text:
                return
        print("%s %s  %s" % (name, package.get("version", ""), description))

    for source in [index.rstrip("/")] if index else [INDEX, UPSTREAM]:
        url = source + "/index.json"
        status = _request(url, _each_package(found))
        if status != 200:
            raise OSError("HTTP %d from %s" % (status, url))
        gc.collect()


def install(package, index=None, target=None, version=None, mpy=True, prompt=True):
    """Install a package and everything it needs.

    Args:
        package (str): A name on an index, or a `github:`, `gitlab:`, `codeberg:`
            or `http(s):` URL, as for `mip.install`.
        index (str): The index to use for the package. By default it looks on
            the OmniPython index, then micropython-lib.
        target (str): The folder to install into. By default the `lib` folder on
            `sys.path`.
        version (str): A version on an index, or a branch or tag for a URL.
        mpy (bool): Take compiled `.mpy` files on MicroPython. Other platforms
            always take `.py`.
        prompt (bool): Whether `connect` may ask for Wi-Fi details.

    Returns:
        bool: `True` once every file has landed.

    Raises:
        OSError: The package or something it needs isn't there, the target can't
            be written, or files are missing afterwards. Unlike `mip.install`,
            which prints and returns, a failed install doesn't pass quietly.
    """
    target = (target or _default_target()).rstrip("/")
    _check_writable(target)
    connect(prompt)

    channel = sys.implementation._mpy & 0xFF if _MP and mpy and hasattr(sys.implementation, "_mpy") else "py"
    plan = _Plan(channel)
    indexes = [index.rstrip("/")] if index else [INDEX, UPSTREAM]
    _walk(plan, package, version, indexes, root=True)
    gc.collect()

    if _MP:
        # Public mip, once per root: it fetches hashed files from the index it
        # is given, and brings each root's own deps from there.
        try:
            import mip
        except ImportError:
            raise OSError("This firmware has no mip: install from a computer with mcuctl")
        for spec, spec_index, spec_version in plan.roots:
            mip.install(spec, index=spec_index, target=target, version=spec_version, mpy=mpy)
    else:
        for path, source, short in plan.files:
            _fetch(path, source, short, target)

    missing = []
    for path, _, _ in plan.files:
        try:
            os.stat(target + "/" + path)
        except OSError:
            missing.append(path)
    if missing:
        raise OSError("%s is partly installed. Missing: %s" % (package, ", ".join(missing)))
    print("Installed %s in %s" % (package, target))
    return True
