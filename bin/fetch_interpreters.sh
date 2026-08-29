#!/usr/bin/env bash
# Fetch the bundled interpreter binaries from a pydevices GitHub Release.
# They are release assets, not git content (modernization Gate 3 decision):
# the repo carries only this script and the Python launchers.
#
#   ./bin/fetch_interpreters.sh            # newest release with interpreter assets
#   ./bin/fetch_interpreters.sh v0.3.8.dev1
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=PyDevices/pydevices
TAG="${1:-}"
FILES=(micropython micropython.exe circuitpython micropython.mjs micropython.wasm)
if [[ -z "$TAG" ]]; then
    TAG=$(gh release list --repo "$REPO" --limit 20 --json tagName \
        --jq '.[].tagName' | while read -r t; do
            gh release view "$t" --repo "$REPO" --json assets \
                --jq '.assets[].name' | grep -qx micropython && { echo "$t"; break; }
        done)
    [[ -n "$TAG" ]] || { echo "No release with interpreter assets found." >&2; exit 1; }
fi
echo "Fetching interpreters from $REPO $TAG"
for f in "${FILES[@]}"; do
    gh release download "$TAG" --repo "$REPO" --pattern "$f" --dir "$HERE" --clobber
done
chmod +x "$HERE"/micropython "$HERE"/micropython.exe "$HERE"/circuitpython "$HERE"/micropython.mjs
echo "Done: $(ls -la "$HERE"/micropython | awk '{print $5}') bytes micropython, etc."
