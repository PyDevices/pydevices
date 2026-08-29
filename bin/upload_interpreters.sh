#!/usr/bin/env bash
# Upload the bundled interpreter binaries to a pydevices GitHub Release as
# assets, along with a generated interpreters.json manifest (sha256, size,
# platform/arch, and interpreter version per file). This is the producer side
# of bin/fetch_interpreters.sh: that script downloads what this one uploads.
#
# Requires the gh CLI, authenticated with permission to upload release assets
# on this repository (gh auth status).
#
#   ./bin/upload_interpreters.sh v0.3.8.dev1
#   ./bin/upload_interpreters.sh v0.3.8.dev1 --clobber   # overwrite existing assets
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=PyDevices/pydevices
TAG="${1:-}"
CLOBBER="${2:-}"

if [[ -z "$TAG" ]]; then
    echo "usage: $0 <tag> [--clobber]" >&2
    exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "error: the gh CLI is required (https://cli.github.com/) and was not found on PATH." >&2
    exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
    echo "error: gh is not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi

FILES=(micropython micropython.exe circuitpython micropython.mjs micropython.wasm)
for f in "${FILES[@]}"; do
    if [[ ! -f "$HERE/$f" ]]; then
        echo "error: $HERE/$f not found; build the interpreters first." >&2
        exit 1
    fi
done

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

MP_VERSION=$("$HERE"/micropython -c "import sys; print(sys.version)" 2>/dev/null)
CP_VERSION=$("$HERE"/circuitpython -c "import sys; print(sys.version)" 2>/dev/null)

MANIFEST="$HERE/interpreters.json"
{
    echo "{"
    echo "  \"tag\": \"$TAG\","
    echo "  \"provenance\": \"built by cmods/build_interpreters.sh on the maintainer workstation\","
    echo "  \"files\": {"

    declare -A PLATFORMS=(
        [micropython]="linux-x86_64"
        [micropython.exe]="windows-amd64"
        [circuitpython]="linux-x86_64"
        [micropython.mjs]="node/browser wasm32"
        [micropython.wasm]="node/browser wasm32"
    )
    declare -A VERSIONS=(
        [micropython]="$MP_VERSION"
        [micropython.exe]="$MP_VERSION"
        [circuitpython]="$CP_VERSION"
        [micropython.mjs]="$MP_VERSION"
        [micropython.wasm]="$MP_VERSION"
    )

    n=${#FILES[@]}
    i=0
    for f in "${FILES[@]}"; do
        i=$((i + 1))
        sha=$(sha256_of "$HERE/$f")
        size=$(stat -c%s "$HERE/$f" 2>/dev/null || stat -f%z "$HERE/$f")
        platform="${PLATFORMS[$f]}"
        version="${VERSIONS[$f]}"
        comma=","
        [[ $i -eq $n ]] && comma=""
        echo "    \"$f\": {"
        echo "      \"sha256\": \"$sha\","
        echo "      \"size\": $size,"
        echo "      \"platform\": \"$platform\","
        echo "      \"version\": \"$version\""
        echo "    }$comma"
    done

    echo "  }"
    echo "}"
} > "$MANIFEST"

echo "Wrote $MANIFEST"

CLOBBER_FLAG=()
[[ "$CLOBBER" == "--clobber" ]] && CLOBBER_FLAG=(--clobber)

echo "Uploading interpreter assets to $REPO $TAG"
gh release upload "$TAG" --repo "$REPO" "${CLOBBER_FLAG[@]}" \
    "${FILES[@]/#/$HERE/}" "$MANIFEST"

echo "Done."
