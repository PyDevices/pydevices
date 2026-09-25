#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Serve the webble gate pages, and collect what they log.

    python tests/bledev_web/serve.py [--port 8765] [--log gate.log]

Then open ``http://localhost:8765/tests/bledev_web/pyodide.html`` (or
``mpy.html``, ``wasm.html``) in Chrome or Edge. Web Bluetooth needs a secure
context, and ``localhost`` is one; to reach it from an Android phone, run
``adb reverse tcp:8765 tcp:8765`` and open the same URL there.

The repository root is served as it is. ``/pyscript/`` comes from the
pyscript-template checkout's vendored PyScript (Pyodide and MicroPython,
offline), and ``/wasm/`` from the workspace's ``bin/`` (the direct MicroPython
WebAssembly build), both found by walking up from this file. Every line a
page logs is POSTed to ``/log``, printed, and appended to ``--log``.
"""

import argparse
import functools
import http.server
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def _find(relative):
    for parent in HERE.parents:
        candidate = parent / relative
        if candidate.exists():
            return candidate
    return None


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(
        http.server.SimpleHTTPRequestHandler.extensions_map,
        **{".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm",
           ".json": "application/json", ".py": "text/plain"},
    )
    mounts = {}
    log_path = None

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        for prefix, directory in self.mounts.items():
            if clean.startswith(prefix):
                return str(Path(directory) / clean[len(prefix):])
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace")
        if self.path.startswith("/log"):
            print(body, flush=True)
            if self.log_path:
                with open(self.log_path, "a") as f:
                    f.write(body + "\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        if "--quiet" not in sys.argv:
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--log", default=None, help="append every logged line here")
    parser.add_argument("--quiet", action="store_true", help="don't log requests")
    args = parser.parse_args()

    pyscript = _find("pyscript-template/vendor/pyscript")
    wasm = _find("bin/micropython.mjs")
    Handler.mounts = {}
    if pyscript:
        Handler.mounts["/pyscript/"] = pyscript
    else:
        print("no pyscript-template/vendor/pyscript found: the PyScript pages won't load", file=sys.stderr)
    if wasm:
        Handler.mounts["/wasm/"] = wasm.parent
    else:
        print("no bin/micropython.mjs found: wasm.html won't load", file=sys.stderr)
    Handler.log_path = args.log

    handler = functools.partial(Handler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer((args.bind, args.port), handler)
    print("serving {} on http://localhost:{}/tests/bledev_web/ (pyscript {}, wasm {})".format(
        ROOT, args.port, pyscript, wasm and wasm.parent), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
