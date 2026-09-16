"""Peak-frequency analysis of a raw s16 capture from the loopback rig."""
import sys
import numpy as np


def analyze(path, rate=16000, channels=2, expect=None, tol_cents=80):
    raw = np.fromfile(path, dtype="<i2").astype(np.float64)
    if channels == 2:
        raw = raw.reshape(-1, 2).mean(axis=1)
    # Drop the first 20% (speaker/codec settling), window the rest.
    raw = raw[int(len(raw) * 0.2):]
    n = len(raw)
    raw = raw - raw.mean()
    rms = float(np.sqrt((raw ** 2).mean()))
    win = raw * np.hanning(n)
    spec = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    # Ignore DC / very low rumble
    lo = np.searchsorted(freqs, 60.0)
    k = lo + int(np.argmax(spec[lo:]))
    # Parabolic interpolation for sub-bin accuracy
    if 0 < k < len(spec) - 1:
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        denom = a - 2 * b + c
        delta = 0.5 * (a - c) / denom if denom else 0.0
    else:
        delta = 0.0
    peak_hz = float((k + delta) * rate / n)
    total = float((spec[lo:] ** 2).sum())
    band = float((spec[max(lo, k - 3):k + 4] ** 2).sum())
    purity = band / total if total else 0.0
    res = {
        "file": path, "rms": rms, "peak_hz": peak_hz,
        "purity": purity, "samples": n,
    }
    if expect:
        cents = 1200 * np.log2(peak_hz / expect) if peak_hz > 0 else -9999
        res["expect_hz"] = expect
        res["cents_off"] = float(cents)
        res["PASS"] = bool(abs(cents) <= tol_cents and rms > 20 and purity > 0.5)
    return res


if __name__ == "__main__":
    path = sys.argv[1]
    rate = int(sys.argv[2]) if len(sys.argv) > 2 else 16000
    ch = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    exp = float(sys.argv[4]) if len(sys.argv) > 4 else None
    r = analyze(path, rate, ch, exp)
    for k, v in r.items():
        print("%-10s %s" % (k, round(v, 3) if isinstance(v, float) else v))
