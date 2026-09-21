#!/bin/bash
# run.sh NAME RATE WIRE CHANNELS TONE EXPECT [DEVICE]
# Play a tone on the T-Embed, capture it on the board's mics, report the peak.
set -u
NAME=$1; RATE=$2; WIRE=$3; CH=$4; TONE=$5; EXPECT=$6; DEV=${7:-COM5}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
MPFTP=$ROOT/../mpftp/scripts/mpftp
OUT=${AUDIO_RIG_OUT:-/tmp/audio_rig}
PY=${AUDIO_RIG_PY:-$ROOT/../audiodsp/.venv/bin/python3}
mkdir -p "$OUT"

cat > "$OUT/rig_cfg.py" <<CFG
RATE = $RATE
WIRE_RATE = $WIRE
CHANNELS = $CH
TONE = $TONE
SECS = 1.0
MIC_GAIN = 35
CFG

"$MPFTP" put -d "$DEV" "$OUT/rig_cfg.py" /rig_cfg.py >/dev/null
LOG=$(timeout 200 "$MPFTP" probe -d "$DEV" --capture /rig_log.txt --wait 35 \
        "${AUDIO_RIG_SCRIPT:-$HERE/loopback.py}" 2>&1)
echo "$LOG" | grep -o 'PHASE_A[^\\]*' | head -1
echo "$LOG" | grep -o 'EXC [^\\]*' | head -1
"$MPFTP" get -d "$DEV" /rig_capture.raw "$OUT/cap_$NAME.raw" >/dev/null
"$PY" "$HERE/analyze.py" "$OUT/cap_$NAME.raw" 16000 2 "$EXPECT"
