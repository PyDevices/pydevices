#!/usr/bin/env bash
# The interpreters attached to a final release: how they are built, and when.
# .github/workflows/release-interpreters.yml calls this; every step also runs
# by hand on Linux or WSL.
#
#   release_interpreters.sh gate <event> <ref> <attach>
#       Decide what a run does. <event> is "release", "workflow_dispatch" or
#       "pull_request";
#       <ref> is the release tag, or for a dispatch the branch or tag to
#       build; <attach> is "true" when a dispatch asks to attach (a release
#       event always attaches). Prints build=, attach= and tag= lines for
#       $GITHUB_OUTPUT. Only a final tag (vX.Y.Z) is ever attached: a dev, a,
#       b or rc release gets no interpreters, and a branch is only ever built.
#
#   release_interpreters.sh build <target> <out-dir>
#       Build one interpreter with micropython-pydevices' build_mp.py and put
#       the files it makes in <out-dir>. Targets:
#         mp-unix     micropython              (linux-x86_64)
#         mp-windows  micropython.exe          (windows-amd64, MinGW cross build)
#         mp-wasm     micropython.mjs, micropython.wasm
#         cp-unix     circuitpython            (linux-x86_64)
#       Environment:
#         MPP_DIR  a micropython-pydevices checkout (required)
#         PYD_DIR  the pydevices tree to build into the interpreters
#                  (default: the one this script lives in)
#         WS_DIR   cp-unix only: a directory holding checkouts of
#                  lvgl-circuitpython, pdwidgets and palettes
#         JOBS     make parallelism (default: nproc)
#
# Every interpreter carries every module, the way the desktop builds are
# documented to be made: download one and run your code with nothing installed.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
FINAL_TAG='^v[0-9]+\.[0-9]+\.[0-9]+$'

gate() {
    local event="${1:?event}" ref="${2:-}" attach="${3:-false}"
    local build=false do_attach=false tag=""
    case "$event" in
        release)
            tag="$ref"
            # Pre-releases (aN, bN, rcN, .devN) are not attached to.
            if [[ "$tag" =~ $FINAL_TAG ]]; then build=true; do_attach=true; fi
            ;;
        workflow_dispatch|pull_request)
            build=true
            if [[ "$attach" == "true" && "$ref" =~ $FINAL_TAG ]]; then
                do_attach=true
                tag="$ref"
            fi
            if [[ "$attach" == "true" && "$do_attach" == "false" ]]; then
                echo "error: will not attach interpreters to '$ref': only a final vX.Y.Z tag gets them" >&2
                return 1
            fi
            ;;
        *)
            echo "error: unknown event '$event'" >&2
            return 1
            ;;
    esac
    echo "build=$build"
    echo "attach=$do_attach"
    echo "tag=$tag"
}

build() {
    local target="${1:?target}" out="${2:?out-dir}"
    : "${MPP_DIR:?set MPP_DIR to a micropython-pydevices checkout}"
    local pyd="${PYD_DIR:-$(cd "$HERE/.." && pwd)}"
    local jobs="${JOBS:-$(nproc)}"
    local mpp
    mpp=$(cd "$MPP_DIR" && pwd)
    mkdir -p "$out"
    out=$(cd "$out" && pwd)

    # The release's own pydevices goes into the interpreter, not the commit
    # modules.lock names: build_mp.py fetches a module only when
    # modules/<name> is missing, and a link there wins.
    if [[ ! -e "$mpp/modules/pydevices" ]]; then
        ln -s "$pyd" "$mpp/modules/pydevices"
    fi

    cd "$mpp"
    case "$target" in
        mp-unix)
            JOBS="$jobs" python3 build_mp.py --port unix --variant pydevices --modules all
            install -m 755 builds/unix/pydevices/micropython "$out/micropython"
            ;;
        mp-windows)
            JOBS="$jobs" python3 build_mp.py --port windows --variant pydevices --modules all
            install -m 755 builds/windows/pydevices/micropython.exe "$out/micropython.exe"
            ;;
        mp-wasm)
            JOBS="$jobs" python3 build_mp.py --port webassembly --variant pydevices --modules all
            sed -i 's/[[:space:]]\+$//' builds/webassembly/pydevices/micropython.mjs
            install -m 755 builds/webassembly/pydevices/micropython.mjs "$out/micropython.mjs"
            install -m 755 builds/webassembly/pydevices/micropython.wasm "$out/micropython.wasm"
            ;;
        cp-unix)
            : "${WS_DIR:?set WS_DIR to a directory with lvgl-circuitpython, pdwidgets and palettes}"
            local ws cp_dir
            ws=$(cd "$WS_DIR" && pwd)
            cp_dir="$HERE/release_interpreters/circuitpython"
            for d in lvgl-circuitpython pdwidgets palettes; do
                [[ -f "$ws/$d/manifest.py" ]] || { echo "error: $ws/$d is not a checkout" >&2; return 1; }
            done
            RELEASE_INTERPRETERS_WS="$ws" JOBS="$jobs" python3 build_mp.py \
                --interpreter circuitpython --port unix \
                --modules "audiodsp,displayif,pygraphics,$ws/lvgl-circuitpython,$cp_dir/unix-extras" \
                FROZEN_MANIFEST="$cp_dir/manifest.py"
            install -m 755 builds/circuitpython/unix/coverage/micropython "$out/circuitpython"
            ;;
        *)
            echo "error: unknown target '$target' (mp-unix, mp-windows, mp-wasm, cp-unix)" >&2
            return 1
            ;;
    esac
    ls -la "$out"
}

cmd="${1:-}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
    gate) gate "$@" ;;
    build) build "$@" ;;
    *) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
