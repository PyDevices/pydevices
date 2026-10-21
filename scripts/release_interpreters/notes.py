#!/usr/bin/env python3
"""The line in a final release's notes that says what the interpreters are built on.

A final attaches desktop interpreters even when they are built on a MicroPython
or CircuitPython pre-release, so the release page says which. The versions come
from the ``built_on`` record in the interpreters.json manifest the same run wrote
(bin/upload_interpreters.sh asks the binaries), not from anywhere else.

    notes.py line interpreters.json              print the line
    notes.py release TAG interpreters.json       put the line at the end of TAG's
                                                 release notes (needs the gh CLI);
                                                 running it again replaces the line
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: The line starts with this, so a second run finds it and replaces it.
MARK = "<!-- interpreters -->"

#: A release is a plain number. Anything after it (preview, alpha, beta, rc, or a
#: build past a tag) is not one.
RELEASE = re.compile(r"v?\d+\.\d+(\.\d+)?")


def _label(version):
    return version if RELEASE.fullmatch(version) else f"{version} (a preview)"


def line(manifest):
    """One sentence for the release notes, from a parsed interpreters.json."""
    built_on = manifest.get("built_on", {})
    mp, cp = built_on.get("micropython"), built_on.get("circuitpython")
    if not mp or not cp:
        raise SystemExit("the manifest's built_on names no MicroPython or no CircuitPython version")
    return f"{MARK}The attached interpreters are built on MicroPython {_label(mp)} and CircuitPython {_label(cp)}."


def with_line(body, text):
    """The release body with text as its last paragraph, replacing an earlier one."""
    kept = [row for row in (body or "").rstrip().splitlines() if not row.startswith(MARK)]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept + ([""] if kept else []) + [text]) + "\n"


def release(tag, manifest_path):
    text = line(json.loads(Path(manifest_path).read_text()))
    body = subprocess.run(["gh", "release", "view", tag, "--json", "body", "--jq", ".body"],
                          check=True, capture_output=True, text=True).stdout
    with tempfile.TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes.md"
        notes.write_text(with_line(body, text))
        subprocess.run(["gh", "release", "edit", tag, "--notes-file", str(notes)], check=True)
    print(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("line")
    s.add_argument("manifest")
    r = sub.add_parser("release")
    r.add_argument("tag")
    r.add_argument("manifest")
    a = ap.parse_args(argv)
    if a.cmd == "line":
        print(line(json.loads(Path(a.manifest).read_text())))
    else:
        release(a.tag, a.manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
