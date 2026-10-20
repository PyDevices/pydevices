#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run a board's smoke test and, if it passes, write its tested record.

With the board package installed on the board (``mip.install`` from the
untested index, see CONTRIBUTING.md), from the repository root:

    python tools/mark_tested.py esp32-s3-touch-lcd-4_3 -d ws://my-board.local \\
        --hardware "Waveshare ESP32-S3-Touch-LCD-4.3, rev 2"

It runs ``tools/smoke/board_smoke.py`` on the board with mpftp, prints each
check, and when every one passed adds a run to the board's ``tested.json``
(the hardware, the firmware the board reported, the date and the checks).
Commit that file in a pull request: once it merges, the board's package and
its drivers publish to the main index. Nothing is written when a check fails.

``-d`` is anything mpftp takes (``ws://HOST``, ``COM5``, ``/dev/ttyACM0``).
``--local MICROPYTHON`` runs a desktop interpreter instead, for the desktop
board configs. ``--path`` is where the package was installed if not the
board's ``/lib``. ``--skip ROLE`` leaves a peripheral out (by default
``usb_device`` and ``can``, which take the USB console away on some boards);
skipped roles are written in the record.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "tools" / "smoke" / "board_smoke.py"
DEFAULT_SKIP = ("usb_device", "can")
TESTED_FILE = "tested.json"


def board_folder(name: str) -> Path:
    sys.path.insert(0, str(ROOT / "tools"))
    import libbuild

    boards = libbuild.find_boards(ROOT)
    if name == libbuild.DESKTOP_BOARD_PACKAGE:
        return ROOT / libbuild.DESKTOP_BOARD_DIR
    if name not in boards:
        raise SystemExit(f"mark_tested: no board package named {name!r}")
    return boards[name]


def smoke_script(skip: list[str], path: str | None) -> str:
    head = f"SMOKE_SKIP = {sorted(skip)!r}\n"
    if path:
        head += f"SMOKE_PATH = {path!r}\n"
    return head + SMOKE.read_text(encoding="utf-8")


def mpftp_command() -> list[str]:
    found = os.environ.get("MPFTP") or shutil.which("mpftp")
    if not found:
        sibling = ROOT.parent / "mpftp" / "scripts" / "mpftp"
        if sibling.is_file():
            found = str(sibling)
    if not found:
        raise SystemExit("mark_tested: mpftp not found (pip install pydevices-mpftp, or set MPFTP)")
    return [found]


def run_smoke(args, script: str) -> str:
    with tempfile.TemporaryDirectory(prefix="smoke-") as tmp:
        path = Path(tmp) / "board_smoke.py"
        path.write_text(script, encoding="utf-8")
        if args.local:
            env = dict(os.environ)
            if args.path:
                env["MICROPYPATH"] = f"{args.path}:.frozen"
            result = subprocess.run([args.local, str(path)], capture_output=True, text=True, timeout=args.timeout, env=env)
            return result.stdout + result.stderr
        command = mpftp_command() + ["run", str(path), "-d", args.device, "--follow"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
        out = result.stdout + result.stderr
        try:
            return json.loads(result.stdout).get("output", out)
        except (json.JSONDecodeError, AttributeError):
            return out


def parse(output: str) -> dict:
    for line in output.splitlines():
        if line.startswith("SMOKE "):
            return json.loads(line[len("SMOKE ") :])
    raise SystemExit(f"mark_tested: the smoke test printed no result. Its output:\n{output}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board", help="the board package, named by its folder")
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("-d", "--device", help="the board, as mpftp names it")
    where.add_argument("--local", metavar="MICROPYTHON", help="run on this desktop interpreter instead")
    parser.add_argument("--hardware", required=True, help="what it ran on, as a person would say it")
    parser.add_argument("--path", help="where the package is installed, if not the board's /lib")
    parser.add_argument("--skip", action="append", default=None, help=f"a peripheral role to leave out (default: {', '.join(DEFAULT_SKIP)})")
    parser.add_argument("--timeout", type=int, default=180, help="seconds to wait for the smoke test (default 180)")
    parser.add_argument("--dry-run", action="store_true", help="run and report, but write nothing")
    args = parser.parse_args(argv)

    folder = board_folder(args.board)
    skip = list(DEFAULT_SKIP) if args.skip is None else args.skip
    result = parse(run_smoke(args, smoke_script(skip, args.path)))
    for check in result["checks"]:
        print(f"  {'ok  ' if check['ok'] else 'FAIL'} {check['check']}: {check['detail']}")
    if result["skipped"]:
        print(f"  skipped: {', '.join(result['skipped'])}")
    print(f"  firmware: {result['firmware']}")
    if not result["board_ok"]:
        print(f"{args.board}: the smoke test failed, so no record was written")
        return 1
    run = {
        "hardware": args.hardware,
        "firmware": result["firmware"],
        "date": datetime.date.today().isoformat(),
        "smoke": "passed",
        "checks": [check["check"] for check in result["checks"]],
        "skipped": result["skipped"],
        "tool": "tools/mark_tested.py",
    }
    if args.dry_run:
        print(json.dumps(run, indent=2))
        return 0
    path = folder / TESTED_FILE
    record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"board": args.board, "runs": []}
    record["runs"] = [r for r in record["runs"] if r.get("hardware") != args.hardware] + [run]
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.board}: passed; wrote {path.relative_to(ROOT)}. Commit it in a pull request.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
