#!/usr/bin/env bash
# Fetch the bundled interpreter binaries from a pydevices GitHub Release.
# They are release assets, not git content (modernization Gate 3 decision):
# the repo carries only this script and the Python launchers.
#
# Requires the gh CLI (https://cli.github.com/), authenticated against
# github.com with at least read access to PyDevices/pydevices releases
# (gh auth login).
#
#   ./bin/fetch_interpreters.sh            # newest release with interpreter assets
#   ./bin/fetch_interpreters.sh v0.3.8.dev1
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=PyDevices/pydevices
TAG="${1:-}"
FILES=(micropython micropython.exe circuitpython micropython.mjs micropython.wasm)
MANIFEST=interpreters.json
SCAN_LIMIT=100

if ! command -v gh >/dev/null 2>&1; then
    echo "error: the gh CLI is required (https://cli.github.com/) and was not found on PATH." >&2
    exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
    echo "error: gh is not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi

# Native binaries (micropython, micropython.exe, circuitpython) only run on
# the platform/arch they were built for; wasm and the Windows binary are the
# portable fallbacks. Warn rather than fail, since a mismatch just means some
# of the fetched files won't run here, not that the fetch itself is wrong.
case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) ;;
    *)
        echo "warning: this looks like $(uname -s)-$(uname -m), not linux-x86_64." >&2
        echo "         micropython, micropython.exe, and circuitpython are native binaries" >&2
        echo "         built for linux-x86_64 / windows-amd64 and won't run here." >&2
        echo "         Use micropython.wasm (+ micropython.mjs) in Node or a browser instead," >&2
        echo "         or micropython.exe under Windows/Wine." >&2
        ;;
esac

if [[ -z "$TAG" ]]; then
    TAG=$(gh release list --repo "$REPO" --limit "$SCAN_LIMIT" --json tagName \
        --jq '.[].tagName' | while read -r t; do
            gh release view "$t" --repo "$REPO" --json assets \
                --jq '.assets[].name' | grep -qx micropython && { echo "$t"; break; }
        done)
    [[ -n "$TAG" ]] || {
        echo "error: no release among the last $SCAN_LIMIT with a 'micropython' asset was found" \
             "in $REPO. Pass a tag explicitly: ./bin/fetch_interpreters.sh vX.Y.Z" >&2
        exit 1
    }
fi
echo "Fetching interpreters from $REPO $TAG"

# Fetch the manifest first so we can verify each binary's sha256 after
# download. Older releases predate the manifest; fall back with a warning
# rather than failing the whole fetch.
HAVE_MANIFEST=1
gh release download "$TAG" --repo "$REPO" --pattern "$MANIFEST" --dir "$HERE" --clobber \
    || HAVE_MANIFEST=0
if [[ "$HAVE_MANIFEST" -eq 0 ]]; then
    echo "warning: $MANIFEST asset not found on $TAG (pre-manifest release);" \
         "skipping sha256 verification." >&2
fi

for f in "${FILES[@]}"; do
    gh release download "$TAG" --repo "$REPO" --pattern "$f" --dir "$HERE" --clobber
done

if [[ "$HAVE_MANIFEST" -eq 1 ]]; then
    echo "Verifying sha256 against $MANIFEST"
    for f in "${FILES[@]}"; do
        expected=$(python3 -c "
import json, sys
with open('$HERE/$MANIFEST') as fh:
    data = json.load(fh)
print(data['files']['$f']['sha256'])
" 2>/dev/null) || expected=""
        [[ -n "$expected" ]] || { echo "warning: no sha256 recorded for $f in $MANIFEST; skipping." >&2; continue; }
        if command -v sha256sum >/dev/null 2>&1; then
            actual=$(sha256sum "$HERE/$f" | awk '{print $1}')
        else
            actual=$(shasum -a 256 "$HERE/$f" | awk '{print $1}')
        fi
        if [[ "$actual" != "$expected" ]]; then
            echo "error: sha256 mismatch for $f" >&2
            echo "  expected: $expected" >&2
            echo "  actual:   $actual" >&2
            exit 1
        fi
    done
    echo "sha256 verified for all files."
fi

# micropython.mjs is a JS module loaded by the browser/Node host (see
# tools/_browser_host.py, which serves it as application/javascript); nothing
# execs it directly, so it does not need the executable bit.
chmod +x "$HERE"/micropython "$HERE"/micropython.exe "$HERE"/circuitpython
echo "Done: $(ls -la "$HERE"/micropython | awk '{print $5}') bytes micropython, etc."
