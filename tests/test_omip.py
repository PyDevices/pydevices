# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""lib/omip.py installs across two indexes, on each interpreter it runs on.

Two small index trees are served from this machine: "ours", whose packages name
what they need from the other under `upstream`, and a stand-in for
micropython-lib. CircuitPython runs get a third, a stand-in for the copy of
Adafruit's bundle. Nothing reaches the internet. CircuitPython's unix build has no
sockets, so its run replaces socketpool, ssl and wifi with fakes that answer from
the same trees: that proves omip's HTTP parsing and file handling, not a real TLS
connection or a real radio.
"""

import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _mprun  # noqa: E402

LIB = _TESTS.parent / "lib"
MPY_CHANNEL = "6"


def write_package(root, name, files, channels=("py", MPY_CHANNEL), **keys):
    """Add a package to an index tree, on the py and bytecode channels unless told others."""
    hashes = []
    for path, text in files.items():
        data = text.encode()
        short = hashlib.sha256(data).hexdigest()[:8]
        out = root / "file" / short[:2] / short
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        hashes.append([path, short])
    body = dict(v=1, version="1.0", hashes=hashes, **keys)
    for channel in channels:
        folder = root / "package" / channel / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "latest.json").write_text(json.dumps(body), encoding="utf-8")


def write_index(root, *packages):
    """Write an index.json as the real indexes do, with nested versions in each package."""
    rows = [
        {"name": name, "version": "1.0", "description": text, "versions": {"py": ["1.0"]}, "path": name}
        for name, text in packages
    ]
    (root / "index.json").write_text(json.dumps({"v": 2, "packages": rows}, indent=2), encoding="utf-8")


def build_indexes(scratch):
    """Returns the (ours, upstream) index trees. `drop_upstream` tests plant faults in them."""
    ours = scratch / "ours"
    upstream = scratch / "upstream"
    write_package(
        upstream,
        "aioble",
        {"aioble/__init__.py": "from .core import NAME\n", "aioble/core.py": 'NAME = "aioble"\n'},
    )
    write_package(upstream, "sdcard", {"sdcard.py": "CARD = True\n"})
    write_package(upstream, "only-upstream", {"only_upstream.py": "HERE = True\n"})
    write_package(
        ours,
        "bledev",
        {"bledev/__init__.py": "import aioble\n"},
        upstream=[["aioble", "latest"]],
        circuitpython=[["asyncio", "latest"]],
    )
    write_package(ours, "gt911", {"gt911.py": "TOUCH = True\n"})
    write_package(ours, "core", {"core.py": "CORE = True\n"})
    write_package(
        ours,
        "board",
        {"board_config.py": "BOARD = True\n"},
        deps=[["core", "latest"], ["gt911", "latest"]],
        upstream=[["sdcard", "latest"]],
    )
    # Its upstream need sits on a dep, not on the package you asked for.
    write_package(ours, "wrapper", {"wrapper.py": "W = True\n"}, deps=[["bledev", "latest"]])
    # asyncio is frozen into every unix MicroPython, so these test skipping what the firmware froze.
    write_package(upstream, "asyncio", {"asyncio/__init__.py": "COPY = True\n", "asyncio/core.py": "COPY = True\n"})
    write_package(ours, "async-user", {"async_user.py": "import asyncio\n"}, upstream=[["asyncio", "latest"]])
    write_package(ours, "frozen-core", {"asyncio/__init__.py": "COPY = True\n"})
    write_package(ours, "on-frozen", {"on_frozen.py": "F = True\n"}, deps=[["frozen-core", "latest"], ["gt911", "latest"]])
    write_package(ours, "broken-dep", {"broken_dep.py": "B = True\n"}, deps=[["no-such-dep", "latest"]])
    write_package(ours, "broken-upstream", {"broken_up.py": "B = True\n"}, upstream=[["no-such-upstream", "latest"]])
    (ours / "repo" / "pkg").mkdir(parents=True)
    (ours / "repo" / "pkg" / "pkg.py").write_text("PKG = True\n", encoding="utf-8")
    (ours / "repo" / "single.py").write_text("SINGLE = True\n", encoding="utf-8")
    (ours / "repo" / "pkg" / "package.json").write_text(
        json.dumps({"urls": [["pkg.py", "pkg.py"]], "deps": [["core", "latest"]], "upstream": [["sdcard", "latest"]]}),
        encoding="utf-8",
    )
    # An app: its own files in a folder of its own, what it needs in the library folder.
    (ours / "repo" / "app").mkdir(parents=True)
    (ours / "repo" / "app" / "__init__.py").write_text("APP = True\n", encoding="utf-8")
    (ours / "repo" / "app" / "app.json").write_text('{"name": "app"}\n', encoding="utf-8")
    (ours / "repo" / "app" / "package.json").write_text(
        json.dumps(
            {
                "target": "apps/app",
                "urls": [["__init__.py", "__init__.py"], ["app.json", "app.json"]],
                "deps": [["bledev", "latest"], ["gt911", "latest"]],
            }
        ),
        encoding="utf-8",
    )
    write_index(ours, ("bledev", "Bluetooth for boards"), ("gt911", 'Touch, with {braces} and a "quote"'))
    write_index(upstream, ("aioble", "Asyncio Bluetooth"), ("sdcard", "SD cards"))
    return ours, upstream


ADAFRUIT_MAJORS = ("9.x", "10.x", "11.x", "12.x")


def build_adafruit(scratch):
    """A stand-in for the copy of Adafruit's bundle: one channel per CircuitPython major version.

    Each channel's adafruit_ticks says which channel it came from.
    """
    root = scratch / "adafruit"
    for channel in ADAFRUIT_MAJORS:
        write_package(root, "adafruit_ticks", {"adafruit_ticks.py": "CHANNEL = %r\n" % channel}, channels=[channel])
    write_package(
        root,
        "asyncio",
        {"asyncio/__init__.py": "from adafruit_ticks import CHANNEL\n"},
        channels=ADAFRUIT_MAJORS,
        deps=[["adafruit_ticks", "latest"]],
    )
    write_package(
        root,
        "adafruit_display_text",
        {"adafruit_display_text/__init__.py": "from adafruit_ticks import CHANNEL\n"},
        channels=ADAFRUIT_MAJORS,
        deps=[["adafruit_ticks", "latest"]],
    )
    # A name both have: ours is the one a bare name gets.
    write_package(root, "gt911", {"gt911.py": "ADAFRUITS = True\n"}, channels=ADAFRUIT_MAJORS)
    write_index(root, ("adafruit_ticks", "Work with intervals and deadlines"), ("asyncio", "Cooperative multitasking"))
    return root


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        self.server.requests.append(self.path)


def serve(directory):
    def handler(*args, **kwargs):
        return _Quiet(*args, directory=str(directory), **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


class Indexes(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix="omip-test-"))
        self.ours_dir, self.upstream_dir = build_indexes(self.scratch)
        self.ours, self.ours_url = serve(self.ours_dir)
        self.upstream, self.upstream_url = serve(self.upstream_dir)
        self.target = self.scratch / "target"
        self.home = self.scratch / "cwd"
        self.home.mkdir()
        # omip.py alone on the path, as it is on a board that got this one file.
        shutil.copy(LIB / "omip.py", self.home / "omip.py")
        self.addCleanup(self._stop)

    def _stop(self):
        self.ours.shutdown()
        self.upstream.shutdown()
        self.ours.server_close()
        self.upstream.server_close()
        for path in self.scratch.rglob("*"):
            if path.is_dir():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
        shutil.rmtree(self.scratch, ignore_errors=True)

    def landed(self):
        return sorted(p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file())


class CPythonInstall(Indexes):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location("omip_under_test", LIB / "omip.py")
        self.omip = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.omip)
        self.omip.INDEX = self.ours_url
        self.omip.UPSTREAM = self.upstream_url

    def install(self, *args, **kwargs):
        kwargs.setdefault("target", str(self.target))
        kwargs.setdefault("prompt", False)
        return self.omip.install(*args, **kwargs)

    def test_a_package_brings_what_it_needs_from_upstream(self):
        self.assertTrue(self.install("bledev"))
        self.assertEqual(self.landed(), ["aioble/__init__.py", "aioble/core.py", "bledev/__init__.py"])

    def test_nothing_is_skipped_where_nothing_is_frozen(self):
        self.assertTrue(self.install("async-user"))
        self.assertEqual(self.landed(), ["async_user.py", "asyncio/__init__.py", "asyncio/core.py"])

    def search(self, *words, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.omip.search(*words, prompt=False, **kwargs)
        return out.getvalue().splitlines()

    def test_search_with_no_words_lists_both_indexes_in_order(self):
        self.assertEqual(
            [line.split()[0] for line in self.search()],
            ["bledev", "gt911", "aioble", "sdcard"],
        )

    def test_search_needs_every_word_in_the_name_or_description(self):
        self.assertEqual(self.search("bluetooth", "ASYNCIO"), ["aioble 1.0  Asyncio Bluetooth"])
        self.assertEqual(self.search("sdcard"), ["sdcard 1.0  SD cards"])
        self.assertEqual(self.search("nothing-has-this"), [])

    def test_search_survives_braces_and_quotes_in_a_description(self):
        self.assertEqual(self.search("braces"), ['gt911 1.0  Touch, with {braces} and a "quote"'])

    def test_search_of_one_index(self):
        self.assertEqual([line.split()[0] for line in self.search(index=self.upstream_url)], ["aioble", "sdcard"])

    def test_search_with_no_index_file_raises(self):
        (self.ours_dir / "index.json").unlink()
        with self.assertRaisesRegex(OSError, "HTTP 404"):
            self.search()

    def test_upstream_on_a_dep_is_found_too(self):
        self.install("wrapper")
        self.assertIn("aioble/core.py", self.landed())

    def test_deps_stay_on_the_index_and_upstream_goes_upstream(self):
        self.install("board", index=self.ours_url)
        self.assertEqual(self.landed(), ["board_config.py", "core.py", "gt911.py", "sdcard.py"])

    def test_a_name_only_upstream_has_is_found_there(self):
        self.install("only-upstream")
        self.assertEqual(self.landed(), ["only_upstream.py"])

    def test_a_given_index_is_the_only_place_it_looks_for_the_package(self):
        with self.assertRaisesRegex(OSError, "Package not found: only-upstream"):
            self.install("only-upstream", index=self.ours_url)

    def test_a_missing_dep_stops_it_before_a_file_is_written(self):
        with self.assertRaisesRegex(OSError, "no-such-dep"):
            self.install("broken-dep")
        self.assertEqual(self.landed(), [])

    def test_a_missing_upstream_stops_it_before_a_file_is_written(self):
        with self.assertRaisesRegex(OSError, "no-such-upstream"):
            self.install("broken-upstream")
        self.assertEqual(self.landed(), [])

    def test_a_package_json_by_url_finds_its_deps_and_upstream(self):
        self.install(self.ours_url + "/repo/pkg")
        self.assertEqual(self.landed(), ["core.py", "pkg.py", "sdcard.py"])

    def test_a_single_file_by_url(self):
        self.install(self.ours_url + "/repo/single.py")
        self.assertEqual(self.landed(), ["single.py"])

    def test_a_file_missing_from_the_index_raises_and_leaves_no_stub(self):
        body = json.loads((self.ours_dir / "package" / "py" / "gt911" / "latest.json").read_text())
        short = body["hashes"][0][1]
        (self.ours_dir / "file" / short[:2] / short).unlink()
        with self.assertRaisesRegex(OSError, "HTTP 404"):
            self.install("gt911")
        self.assertEqual(self.landed(), [])

    def test_a_second_run_downloads_nothing_again(self):
        self.install("bledev")
        before = [r for r in self.ours.requests + self.upstream.requests if "/file/" in r]
        self.assertEqual(len(before), 3)
        self.install("bledev")
        after = [r for r in self.ours.requests + self.upstream.requests if "/file/" in r]
        self.assertEqual(after, before)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs a real permission check")
    def test_a_target_it_cant_write_is_named_before_any_request(self):
        self.target.mkdir()
        self.target.chmod(0o555)
        with self.assertRaisesRegex(OSError, "Can't write to"):
            self.install("bledev")
        self.assertEqual(self.ours.requests, [])

    def test_a_name_can_carry_its_version(self):
        write_package(self.ours_dir, "versioned", {"versioned.py": "V = 2\n"})
        folder = self.ours_dir / "package" / "py" / "versioned"
        (folder / "latest.json").rename(folder / "2.0.json")
        self.install("versioned@2.0")
        self.assertEqual((self.target / "versioned.py").read_text(), "V = 2\n")

    def apps_landed(self):
        apps = self.scratch / "apps"
        return sorted(p.relative_to(apps).as_posix() for p in apps.rglob("*") if p.is_file())

    def test_a_package_with_its_own_folder_lands_there_and_its_needs_in_lib(self):
        self.install(self.ours_url + "/repo/app")
        self.assertEqual(self.apps_landed(), ["app/__init__.py", "app/app.json"])
        self.assertEqual(self.landed(), ["aioble/__init__.py", "aioble/core.py", "bledev/__init__.py", "gt911.py"])

    def test_own_folder_beside_the_library_folder(self):
        beside = self.omip._beside
        self.assertEqual(beside("/lib", "apps/home"), "/apps/home")
        self.assertEqual(beside("/flash/lib", "apps/home"), "/flash/apps/home")
        self.assertEqual(beside("lib", "apps/home/"), "apps/home")
        self.assertEqual(beside("/lib", "/sd/apps/home/"), "/sd/apps/home")

    def test_url_base_is_where_relative_urls_are_found(self):
        site = self.ours_dir / "site"
        (site / "src").mkdir(parents=True)
        (site / "src" / "hello.py").write_text("HELLO = True\n", encoding="utf-8")
        (site / "packages").mkdir()
        (site / "packages" / "demo.json").write_text(json.dumps({"urls": [["hello.py", "./src/hello.py"]]}), encoding="utf-8")
        manifest = self.ours_url + "/site/packages/demo.json"
        with self.assertRaisesRegex(OSError, "HTTP 404"):
            self.install(manifest)
        self.install(manifest, url_base=self.ours_url + "/site/")
        self.assertEqual(self.landed(), ["hello.py"])


# What a browser hands Pyodide for a request made as x-user-defined: one
# character per byte, the bytes from 0x80 up moved to U+F780 and on.
FAKE_JS = """
from urllib.error import HTTPError
from urllib.request import urlopen
class XMLHttpRequest:
    @classmethod
    def new(cls):
        return cls()
    def open(self, method, url, asynchronous):
        assert method == "GET" and asynchronous is False
        self.url = url
    def overrideMimeType(self, mime):
        self.mime = mime
    def send(self, body):
        try:
            with urlopen(self.url) as response:
                data = response.read()
                self.status = response.status
        except HTTPError as exc:
            data, self.status = b"", exc.code
        if self.mime == "text/plain; charset=x-user-defined":
            self.responseText = "".join(chr(b) if b < 0x80 else chr(0xF700 + b) for b in data)
        else:
            self.responseText = data.decode("utf-8", "replace")
"""


class BrowserInstall(Indexes):
    """omip under Pyodide, where the browser makes the requests."""

    def setUp(self):
        super().setUp()
        fake = Path(tempfile.mkdtemp(prefix="omip-js-"))
        self.addCleanup(shutil.rmtree, fake, ignore_errors=True)
        (fake / "js.py").write_text(FAKE_JS, encoding="utf-8")
        sys.path.insert(0, str(fake))
        self.addCleanup(sys.path.remove, str(fake))
        self.addCleanup(sys.modules.pop, "js", None)
        # The fake keeps the real urlopen; Pyodide's own can't open a socket.
        importlib.import_module("js")
        refuse = mock.patch("urllib.request.urlopen", side_effect=OSError("no sockets in a browser"))
        refuse.start()
        self.addCleanup(refuse.stop)
        platform = sys.platform
        sys.platform = "emscripten"
        try:
            spec = importlib.util.spec_from_file_location("omip_in_browser", LIB / "omip.py")
            self.omip = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.omip)
        finally:
            sys.platform = platform
        self.omip.INDEX = self.ours_url
        self.omip.UPSTREAM = self.upstream_url

    def test_every_byte_arrives_through_the_browser(self):
        data = bytes(range(256)) * 4
        short = hashlib.sha256(data).hexdigest()[:8]
        (self.ours_dir / "file" / short[:2]).mkdir(parents=True, exist_ok=True)
        (self.ours_dir / "file" / short[:2] / short).write_bytes(data)
        folder = self.ours_dir / "package" / "py" / "blob"
        folder.mkdir(parents=True)
        (folder / "latest.json").write_text(json.dumps({"hashes": [["blob.bin", short]]}), encoding="utf-8")
        self.omip.install("blob", target=str(self.target), prompt=False)
        self.assertEqual((self.target / "blob.bin").read_bytes(), data)

    def test_a_package_and_its_upstream_need(self):
        self.omip.install("bledev", target=str(self.target), prompt=False)
        self.assertEqual(self.landed(), ["aioble/__init__.py", "aioble/core.py", "bledev/__init__.py"])

    def test_not_found_says_so(self):
        with self.assertRaisesRegex(OSError, "Package not found: nothing-here"):
            self.omip.install("nothing-here", target=str(self.target), prompt=False)


MP_INSTALL = """
import sys
import omip
omip.UPSTREAM = {upstream!r}
# Ahead of .frozen, so a firmware that froze bledev or aioble still installs them here.
sys.path.insert(0, {target!r})
print("RESULT", omip.install({package!r}, index={index!r}, target={target!r}, prompt=False))
import aioble
print("IMPORTED", aioble.NAME)
"""

MP_FROZEN = """
import sys
import omip
omip.UPSTREAM = {upstream!r}
{before}
print("RESULT", omip.install({package!r}, index={index!r}, target={target!r}, prompt=False{extra}))
import asyncio
print("ASYNCIO", getattr(asyncio, "COPY", "frozen"))
"""

MP_STOCK = """
import mip
mip.install({package!r}, index={index!r}, target={target!r})
"""

# A radio with a script: what it answers, and a log of what it was told.
FAKE_NETWORK = """
STA_IF = 0
class WLAN:
    connected = {connected}
    joins = {joins}
    def __init__(self, kind): pass
    def active(self, on=None): return True
    def disconnect(self): pass
    def isconnected(self): return WLAN.connected
    def connect(self, ssid, password):
        print("JOIN", ssid, password)
        if ssid in WLAN.joins:
            WLAN.connected = True
"""

MP_CONNECT = """
import omip
print("ONLINE", omip.connect(timeout=1))
"""


MP_SEARCH = """
import omip
omip.INDEX = {ours!r}
omip.UPSTREAM = {upstream!r}
omip.search(*{words!r}, prompt=False)
print("DONE")
"""


class MicroPythonRun(Indexes):
    def run_mp(self, script, *, stdin=""):
        interpreter = _mprun.need_micropython(self)
        env = dict(os.environ, MICROPYPATH="%s:.frozen" % self.home)
        env.pop("MICROPYINSPECT", None)
        result = subprocess.run(
            [interpreter, "-c", script],
            cwd=str(self.home),
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout + result.stderr

    def script(self, template, package="bledev", index=None):
        return template.format(
            upstream=self.upstream_url,
            package=package,
            index=index or self.ours_url,
            target=str(self.target),
        )

    def test_install_lands_both_and_import_works(self):
        out = self.run_mp(self.script(MP_INSTALL))
        self.assertIn("RESULT True", out)
        self.assertIn("IMPORTED aioble", out)
        self.assertEqual(self.landed(), ["aioble/__init__.py", "aioble/core.py", "bledev/__init__.py"])

    def test_a_version_and_a_url_base(self):
        write_package(self.ours_dir, "versioned", {"versioned.py": "V = 2\n"})
        folder = self.ours_dir / "package" / MPY_CHANNEL / "versioned"
        (folder / "latest.json").rename(folder / "2.0.json")
        site = self.ours_dir / "site"
        (site / "src").mkdir(parents=True)
        (site / "src" / "hello.py").write_text("HELLO = True\n", encoding="utf-8")
        (self.ours_dir / "demo.json").write_text(json.dumps({"urls": [["hello.py", "./src/hello.py"]]}), encoding="utf-8")
        out = self.run_mp(
            "import omip\n"
            "omip.install('versioned@2.0', index=%r, target=%r, prompt=False)\n"
            "omip.install(%r, url_base=%r, target=%r, prompt=False)\n"
            % (self.ours_url, str(self.target), self.ours_url + "/demo.json", self.ours_url + "/site", str(self.target))
        )
        self.assertNotIn("Traceback", out, out)
        self.assertEqual(self.landed(), ["hello.py", "versioned.py"])

    def test_a_package_with_its_own_folder_on_micropython(self):
        out = self.run_mp(
            # The target ahead of .frozen, as in MP_INSTALL.
            "import sys\nimport omip\nomip.INDEX = %r\nomip.UPSTREAM = %r\nsys.path.insert(0, %r)\n"
            "print('RESULT', omip.install(%r, target=%r, prompt=False))\n"
            % (self.ours_url, self.upstream_url, str(self.target), self.ours_url + "/repo/app", str(self.target))
        )
        self.assertIn("RESULT True", out)
        self.assertIn("Installed %s/repo/app in %s" % (self.ours_url, self.scratch / "apps" / "app"), out)
        apps = self.scratch / "apps"
        landed = sorted(p.relative_to(apps).as_posix() for p in apps.rglob("*") if p.is_file())
        self.assertEqual(landed, ["app/__init__.py", "app/app.json"])
        self.assertEqual(self.landed(), ["aioble/__init__.py", "aioble/core.py", "bledev/__init__.py", "gt911.py"])

    def test_the_root_folder_stays_the_root_for_mip(self):
        # mip reads an empty target as its default, /lib: "/" has to reach it as "/".
        out = self.run_mp(
            "import omip, mip\nomip._check_writable = lambda folder: None\n"
            "mip.install = lambda *args, **kw: print('MIP', kw['target'])\n"
            "try:\n    omip.install(%r, target='/', prompt=False)\nexcept OSError as exc:\n    print('NOT THERE', exc)\n"
            % (self.ours_url + "/repo/single.py")
        )
        self.assertIn("MIP /\n", out)

    def test_search_reads_both_indexes(self):
        out = self.run_mp(MP_SEARCH.format(ours=self.ours_url, upstream=self.upstream_url, words=("BLUETOOTH",)))
        self.assertIn("bledev 1.0  Bluetooth for boards", out)
        self.assertIn("aioble 1.0  Asyncio Bluetooth", out)
        self.assertNotIn("sdcard", out)
        self.assertIn("DONE", out)

    def test_it_asks_for_the_bytecode_channel(self):
        self.run_mp(self.script(MP_INSTALL))
        self.assertIn("/package/%s/bledev/latest.json" % MPY_CHANNEL, self.ours.requests)
        self.assertIn("/package/%s/aioble/latest.json" % MPY_CHANNEL, self.upstream.requests)

    def test_stock_mip_ignores_the_key_as_it_always_has(self):
        out = self.run_mp(self.script(MP_STOCK))
        self.assertIn("Done", out)
        self.assertNotIn("partially", out)
        self.assertEqual(self.landed(), ["bledev/__init__.py"])
        self.assertEqual(self.upstream.requests, [])

    def frozen(self, package, before="", extra=""):
        script = MP_FROZEN.format(
            upstream=self.upstream_url, package=package, index=self.ours_url, target=str(self.target),
            before=before, extra=extra,
        )
        return self.run_mp(script)

    def test_an_upstream_need_the_firmware_froze_is_skipped(self):
        out = self.frozen("async-user")
        self.assertIn("Skipping asyncio: it's frozen into this firmware", out)
        self.assertIn("RESULT True", out)
        self.assertIn("ASYNCIO frozen", out)
        self.assertEqual(self.landed(), ["async_user.py"])
        self.assertNotIn("/package/%s/asyncio/latest.json" % MPY_CHANNEL, self.ours.requests)

    def test_a_frozen_dep_is_skipped_and_the_rest_of_its_root_still_lands(self):
        out = self.frozen("on-frozen")
        self.assertIn("Skipping frozen-core", out)
        self.assertIn("RESULT True", out)
        self.assertEqual(self.landed(), ["gt911.py", "on_frozen.py"])

    def test_a_package_wholly_frozen_installs_nothing_and_says_so(self):
        out = self.frozen("frozen-core")
        self.assertIn("Nothing to install: the firmware has frozen-core frozen in", out)
        self.assertIn("RESULT True", out)
        self.assertEqual(self.landed(), [])

    def test_force_installs_it_anyway(self):
        out = self.frozen("on-frozen", extra=", force=True")
        self.assertNotIn("Skipping", out)
        self.assertEqual(self.landed(), ["asyncio/__init__.py", "gt911.py", "on_frozen.py"])

    def test_a_target_ahead_of_frozen_on_the_path_gets_the_copy(self):
        out = self.frozen("async-user", before="sys.path.insert(0, %r)" % str(self.target))
        self.assertNotIn("Skipping", out)
        self.assertIn("ASYNCIO True", out)
        self.assertEqual(self.landed(), ["async_user.py", "asyncio/__init__.py", "asyncio/core.py"])

    def test_a_missing_upstream_raises_on_micropython_too(self):
        out = self.run_mp(self.script(MP_INSTALL, package="broken-upstream"))
        self.assertIn("no-such-upstream", out)
        self.assertNotIn("RESULT", out)
        self.assertEqual(self.landed(), [])

    # Wi-Fi, with a fake network module.

    def connect_with(self, *, connected=False, joins=("home",), stdin="", files=None):
        (self.home / "network.py").write_text(
            FAKE_NETWORK.format(connected=connected, joins=list(joins)), encoding="utf-8"
        )
        for name, text in (files or {}).items():
            (self.home / name).write_text(text, encoding="utf-8")
        return self.run_mp(MP_CONNECT, stdin=stdin)

    def test_already_connected_does_nothing(self):
        out = self.connect_with(connected=True, files={"secrets.py": 'WIFI_SSID = "home"\n'})
        self.assertIn("ONLINE True", out)
        self.assertNotIn("JOIN", out)

    def test_a_secrets_module_is_used(self):
        out = self.connect_with(files={"secrets.py": 'WIFI_SSID = "home"\nWIFI_PASSWORD = "pw"\n'})
        self.assertIn("JOIN home pw", out)
        self.assertIn("ONLINE True", out)

    def test_with_nothing_saved_it_asks_and_saves_nothing_unless_told(self):
        out = self.connect_with(stdin="home\npw\nn\n")
        self.assertIn("JOIN home pw", out)
        self.assertIn("ONLINE True", out)
        self.assertFalse((self.home / "secrets.py").exists())

    def test_a_typed_password_is_saved_when_you_say_yes(self):
        self.connect_with(stdin="home\npw\ny\n")
        self.assertEqual((self.home / "secrets.py").read_text(), "WIFI_SSID = 'home'\nWIFI_PASSWORD = 'pw'\n")

    def test_enter_skips_wifi(self):
        out = self.connect_with(stdin="\n")
        self.assertNotIn("JOIN", out)
        self.assertIn("ONLINE False", out)

    def test_a_saved_network_out_of_range_falls_through_to_asking(self):
        out = self.connect_with(joins=("cafe",), files={"secrets.py": 'WIFI_SSID = "home"\n'}, stdin="cafe\npw\nn\n")
        self.assertIn("JOIN home", out)
        self.assertIn("JOIN cafe pw", out)
        self.assertIn("ONLINE True", out)


FAKE_WIFI = """
class Radio:
    ipv4_address = {address}
    def connect(self, ssid, password, timeout=None):
        print("JOIN", ssid, password)
        Radio.ipv4_address = "10.0.0.2"
radio = Radio()
"""

FAKE_SSL = """
class Context:
    def wrap_socket(self, sock, server_hostname=None):
        print("TLS", server_hostname)
        return sock
def create_default_context():
    return Context()
"""

# Answers from the index trees on disk, in small pieces, as a real socket would.
FAKE_SOCKETPOOL = """
TREES = {trees}
class Socket:
    def __init__(self):
        self.out = b""
        self.pos = 0
        self.host = None
    def settimeout(self, seconds): pass
    def connect(self, address):
        self.host = address[0]
    def send(self, data):
        data = bytes(data)
        line = data.split(b"\\r\\n")[0].decode()
        path = line.split(" ")[1]
        assert line.endswith("HTTP/1.0"), line
        if path == "/moved":
            self.out = b"HTTP/1.0 301 Moved\\r\\nLocation: /package/py/bledev/latest.json\\r\\n\\r\\n"
            return len(data)
        try:
            with open(TREES[self.host] + path, "rb") as f:
                body = f.read()
            length = b"" if b"NOLENGTH" in body else b"Content-Length: %d\\r\\n" % len(body)
            self.out = b"HTTP/1.0 200 OK\\r\\nServer: fake\\r\\n" + length + b"\\r\\n" + body
        except OSError:
            self.out = b"HTTP/1.0 404 Not Found\\r\\nContent-Length: 0\\r\\n\\r\\n"
        return len(data)
    def recv_into(self, buf):
        if b"DROPPED" in self.out and self.pos > len(self.out) // 2:
            raise OSError(116)
        n = min(7, len(buf), len(self.out) - self.pos)
        buf[:n] = self.out[self.pos:self.pos + n]
        self.pos += n
        return n
    def close(self): pass
class SocketPool:
    AF_INET = 2
    SOCK_STREAM = 1
    def __init__(self, radio): pass
    def socket(self, family, kind):
        return Socket()
"""

CP_INSTALL = """
import omip
omip.INDEX = "https://ours.test"
omip.ADAFRUIT = "https://adafruit.test"
omip.UPSTREAM = "https://upstream.test"
print("RESULT", omip.install({package!r}, target={target!r}, prompt=False))
"""


class CircuitPythonRun(Indexes):
    def setUp(self):
        super().setUp()
        self.adafruit_dir = build_adafruit(self.scratch)

    def run_cp(self, script, *, stdin="", address='"10.0.0.1"', env=None):
        interpreter = os.environ.get("PYDEVICES_CIRCUITPYTHON") or shutil.which("circuitpython")
        if not interpreter:
            found = [p / "bin" / "circuitpython" for p in _TESTS.parents if (p / "bin" / "circuitpython").is_file()]
            interpreter = str(found[0]) if found else None
        if not interpreter:
            self.skipTest("no circuitpython binary: this check did NOT run on CircuitPython")
        trees = {"ours.test": str(self.ours_dir), "upstream.test": str(self.upstream_dir), "adafruit.test": str(self.adafruit_dir)}
        (self.home / "wifi.py").write_text(FAKE_WIFI.format(address=address), encoding="utf-8")
        (self.home / "ssl.py").write_text(FAKE_SSL, encoding="utf-8")
        (self.home / "socketpool.py").write_text(FAKE_SOCKETPOOL.format(trees=repr(trees)), encoding="utf-8")
        env = dict(os.environ, MICROPYPATH="%s:.frozen" % self.home, **(env or {}))
        result = subprocess.run(
            [interpreter, "-c", script], cwd=str(self.home), env=env, input=stdin, capture_output=True, text=True, timeout=60
        )
        return result.stdout + result.stderr

    def script(self, package="bledev"):
        return CP_INSTALL.format(package=package, target=str(self.target))

    def major(self):
        out = self.run_cp('import sys\nprint("MAJOR %d.x" % sys.implementation.version[0])\n')
        return out.split("MAJOR ")[1].split()[0]

    def test_takes_the_py_channel_and_adafruits_libraries_in_place_of_micropythons(self):
        out = self.run_cp(self.script())
        self.assertIn("RESULT True", out, out)
        self.assertIn("TLS ours.test", out)
        self.assertIn("Skipping aioble", out)
        self.assertEqual(self.landed(), ["adafruit_ticks.py", "asyncio/__init__.py", "bledev/__init__.py"])
        self.assertEqual((self.target / "bledev" / "__init__.py").read_text(), "import aioble\n")

    def test_a_bare_name_ours_lacks_comes_from_adafruits_bundle_for_this_major(self):
        out = self.run_cp(
            self.script("adafruit_display_text")
            + "import sys\nsys.path.insert(0, %r)\nimport adafruit_display_text\n"
            "print('IMPORTED', adafruit_display_text.CHANNEL)\n" % str(self.target)
        )
        self.assertIn("RESULT True", out, out)
        self.assertIn("IMPORTED %s" % self.major(), out)
        self.assertEqual(self.landed(), ["adafruit_display_text/__init__.py", "adafruit_ticks.py"])

    def test_ours_comes_first_for_a_name_both_have(self):
        out = self.run_cp(self.script("gt911"))
        self.assertIn("RESULT True", out, out)
        self.assertEqual((self.target / "gt911.py").read_text(), "TOUCH = True\n")

    def test_a_version_adafruits_bundle_lacks_says_where_it_looked(self):
        out = self.run_cp(self.script("adafruit_ticks@0.1"))
        self.assertIn("Package not found: adafruit_ticks (looked on https://ours.test, https://adafruit.test", out)
        self.assertNotIn("RESULT", out)

    def test_deps_arrive_byte_for_byte_through_the_http_parser(self):
        big = "".join("line %d\n" % i for i in range(2000))
        write_package(self.ours_dir, "big", {"big.py": big})
        out = self.run_cp(self.script("big"))
        self.assertIn("RESULT True", out, out)
        self.assertEqual((self.target / "big.py").read_text(), big)

    def test_a_body_with_no_length_reads_to_the_end(self):
        write_package(self.ours_dir, "nolength", {"n.py": "# NOLENGTH\nX = 1\n"})
        out = self.run_cp(self.script("nolength"))
        self.assertIn("RESULT True", out, out)
        self.assertEqual((self.target / "n.py").read_text(), "# NOLENGTH\nX = 1\n")

    def test_a_redirect_is_followed(self):
        out = self.run_cp(
            'import omip\nprint(omip._read_json("https://ours.test/moved")["version"])\n'
        )
        self.assertIn("1.0", out)

    def test_a_dropped_connection_names_the_url_and_leaves_no_partial_file(self):
        write_package(self.ours_dir, "dropped", {"d.py": "# DROPPED\n" + "X = 1\n" * 200})
        out = self.run_cp(self.script("dropped"))
        self.assertIn("Couldn't get https://ours.test/file/", out)
        self.assertIn("116", out)
        self.assertNotIn("RESULT", out)
        self.assertEqual(self.landed(), [])

    def test_search_through_the_http_parser(self):
        out = self.run_cp(
            'import omip\nomip.INDEX = "https://ours.test"\nomip.UPSTREAM = "https://upstream.test"\n'
            'omip.ADAFRUIT = "https://adafruit.test"\n'
            'omip.search(prompt=False)\nprint("DONE")\n'
        )
        self.assertIn("DONE", out, out)
        names = [line.split()[0] for line in out.splitlines() if " 1.0  " in line]
        self.assertEqual(names, ["bledev", "gt911", "adafruit_ticks", "asyncio", "aioble", "sdcard"])

    def test_not_found_says_so(self):
        out = self.run_cp(self.script("no-such"))
        self.assertIn("Package not found: no-such", out)
        self.assertNotIn("RESULT", out)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs a real permission check")
    def test_a_read_only_drive_says_what_to_do(self):
        self.target.mkdir()
        self.target.chmod(0o555)
        out = self.run_cp(self.script())
        self.assertIn("usually because", out)
        self.assertIn("boot.py", out)
        self.assertIn("circup", out)
        self.assertNotIn("RESULT", out)

    def test_it_joins_with_wifi_radio_when_offline(self):
        (self.home / "secrets.py").write_text('secrets = {"ssid": "home", "password": "pw"}\n', encoding="utf-8")
        out = self.run_cp(
            'import omip\nprint("ONLINE", omip.connect())\n',
            address="None",
        )
        self.assertIn("JOIN home pw", out)
        self.assertIn("ONLINE True", out)

    def ask_on_cp(self, serial, stdin):
        (self.home / "supervisor.py").write_text(
            "class runtime:\n    serial_connected = %r\n" % serial, encoding="utf-8"
        )
        return self.run_cp('import omip\nprint("ONLINE", omip.connect())\n', address="None", stdin=stdin)

    def test_it_asks_on_the_serial_console_and_saves_to_settings_toml(self):
        out = self.ask_on_cp(True, 'home\npw"x\ny\n')
        self.assertIn('JOIN home pw"x', out)
        self.assertEqual(
            (self.home / "settings.toml").read_text(),
            'CIRCUITPY_WIFI_SSID = "home"\nCIRCUITPY_WIFI_PASSWORD = "pw\\"x"\n',
        )

    def test_with_no_serial_console_it_doesnt_ask(self):
        out = self.ask_on_cp(False, "home\npw\ny\n")
        self.assertNotIn("JOIN", out)
        self.assertIn("ONLINE False", out)

    def test_settings_toml_is_used(self):
        # CircuitPython's os.getenv is what reads the file on a board; the unix
        # build reads the environment, which proves omip asks for the right names.
        out = self.run_cp(
            'import omip\nprint("ONLINE", omip.connect())\n',
            address="None",
            env={"CIRCUITPY_WIFI_SSID": "home", "CIRCUITPY_WIFI_PASSWORD": "pw"},
        )
        self.assertIn("JOIN home pw", out)

    def test_the_mip_alias_is_omip(self):
        (self.home / "mip.py").write_text(
            (LIB.parent / "board_configs" / "cp" / "mip.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        out = self.run_cp(
            'import mip, omip\nprint("SAME", mip.install is omip.install)\n'
        )
        self.assertIn("SAME True", out)


if __name__ == "__main__":
    unittest.main()
