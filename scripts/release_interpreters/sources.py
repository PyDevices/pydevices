#!/usr/bin/env python3
"""The pins behind a final release's interpreters.

scripts/release_interpreters/sources.lock names the commits of
micropython-pydevices and lvgl-circuitpython that the interpreters are built
from. This reads that file for .github/workflows/release-interpreters.yml and
bin/upload_interpreters.sh, moves it forward, and writes the "sources" record
that goes into the attached interpreters.json.

    sources.py pins                      print mpp=<sha> and lvgl_cp=<sha> lines
                                         (the workflow appends them to $GITHUB_OUTPUT)
    sources.py bump [--dry-run]          move both pins to the tips of their default branches
    sources.py stale                     print a ::warning:: for each pin behind its default branch
    sources.py verify <name> <dir>       fail unless <dir>'s HEAD is <name>'s pinned commit
    sources.py record --mpp DIR --lvgl-circuitpython DIR --pydevices DIR [--pydevices-ref TAG]
                                         print the "sources" JSON for those checkouts

Every command takes --lock FILE to read another lock file.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = HERE / "sources.lock"
NAMES = ("micropython-pydevices", "lvgl-circuitpython")
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def read_lock(path):
    """Rows of a lock file as {name: (url, commit)}, comments and blanks skipped."""
    rows = {}
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise SystemExit(f"{path}:{n}: want 'name url commit', got {line!r}")
        name, url, commit = parts
        if name in rows:
            raise SystemExit(f"{path}:{n}: {name} is listed twice")
        rows[name] = (url, commit)
    return rows


def pins(path=LOCK):
    """The two pins, checked: both present, each a full commit hash."""
    rows = read_lock(path)
    for name in NAMES:
        if name not in rows:
            raise SystemExit(f"{path}: no pin for {name}")
        if not FULL_SHA.fullmatch(rows[name][1]):
            raise SystemExit(f"{path}: {name} must be a full 40-character commit, got {rows[name][1]!r}")
    return {name: rows[name] for name in NAMES}


def remote_head(url):
    """The commit at the tip of a repository's default branch."""
    out = subprocess.run(["git", "ls-remote", url, "HEAD"], check=True, capture_output=True, text=True).stdout
    sha = out.split()[0] if out.split() else ""
    if not FULL_SHA.fullmatch(sha):
        raise SystemExit(f"could not read the default branch of {url}")
    return sha


def bump(path=LOCK, dry_run=False):
    """Move both pins to their repositories' default-branch tips; keep the file's comments."""
    current = pins(path)
    lines = Path(path).read_text().splitlines(keepends=True)
    for name, (url, old) in current.items():
        new = remote_head(url)
        print(f"{name}: {old[:12]} -> {new[:12]}" + ("" if new != old else " (already current)"))
        for i, line in enumerate(lines):
            if line.split("#", 1)[0].split()[:1] == [name]:
                lines[i] = line.replace(old, new)
    if not dry_run:
        Path(path).write_text("".join(lines))
    return 0


def stale(path=LOCK):
    for name, (url, commit) in pins(path).items():
        try:
            head = remote_head(url)
        except (SystemExit, subprocess.CalledProcessError):
            continue
        if head != commit:
            print(f"::warning title={name} pin is behind::The interpreters build from {name} {commit[:12]}, "
                  f"but its default branch is at {head[:12]}. Run sources.py bump to move the pin before a final.")
    return 0


def git_head(directory):
    return subprocess.run(["git", "-C", str(directory), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def verify(name, directory, path=LOCK):
    want = pins(path)[name][1]
    got = git_head(directory)
    if got != want:
        raise SystemExit(f"{name} is at {got}, but sources.lock pins {want}")
    print(f"{name} is at its pin, {want}")
    return 0


def record(mpp_dir, lvgl_dir, pydevices_dir, pydevices_ref, path=LOCK):
    """The "sources" object of interpreters.json: every commit the interpreters were built from.

    It reads the checkouts themselves. The MicroPython commit, the CircuitPython
    version and the modules come from micropython-pydevices' own locks. "pinned"
    says whether both checkouts are the commits sources.lock names: a final's
    attachments always are, a hand-run build of another ref says false.
    """
    mpp_dir = Path(mpp_dir)
    mpp_commit = git_head(mpp_dir)
    lvgl_commit = git_head(lvgl_dir)
    pydevices_commit = git_head(pydevices_dir)
    want = pins(path)
    pinned = (mpp_commit == want["micropython-pydevices"][1] and lvgl_commit == want["lvgl-circuitpython"][1])
    modules = {}
    for name, (_, commit) in read_lock(mpp_dir / "modules.lock").items():
        modules[name] = commit
    deps = {name: version for name, (_, version) in read_lock(mpp_dir / "deps.lock").items()}
    # The release's own pydevices goes in, not the commit modules.lock names.
    modules.pop("pydevices", None)
    pydevices = {"commit": pydevices_commit}
    if pydevices_ref:
        pydevices["ref"] = pydevices_ref
    return {
        "pinned": pinned,
        "pydevices": pydevices,
        "micropython-pydevices": {"commit": mpp_commit},
        "lvgl-circuitpython": {"commit": lvgl_commit},
        "micropython": {"commit": (mpp_dir / "UPSTREAM").read_text().strip()},
        "circuitpython": {"version": deps.get("circuitpython", "")},
        "modules": modules,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lock", default=str(LOCK))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pins")
    b = sub.add_parser("bump")
    b.add_argument("--dry-run", action="store_true")
    sub.add_parser("stale")
    v = sub.add_parser("verify")
    v.add_argument("name", choices=NAMES)
    v.add_argument("directory")
    r = sub.add_parser("record")
    r.add_argument("--mpp", required=True)
    r.add_argument("--lvgl-circuitpython", required=True)
    r.add_argument("--pydevices", required=True)
    r.add_argument("--pydevices-ref", default="")
    a = ap.parse_args(argv)
    if a.cmd == "pins":
        p = pins(a.lock)
        print(f"mpp={p['micropython-pydevices'][1]}")
        print(f"lvgl_cp={p['lvgl-circuitpython'][1]}")
        return 0
    if a.cmd == "bump":
        return bump(a.lock, a.dry_run)
    if a.cmd == "stale":
        return stale(a.lock)
    if a.cmd == "verify":
        return verify(a.name, a.directory, a.lock)
    print(json.dumps(record(a.mpp, a.lvgl_circuitpython, a.pydevices, a.pydevices_ref, a.lock), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
