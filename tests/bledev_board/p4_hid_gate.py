# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The HID gate, repeated, with a board as the device and the P4 as the host.

Runs on Windows Python with pyserial, driving both boards' friendly REPLs over
their UARTs (``uart_rig.py``). Set up once with mpftp:

* the device board (an S3): ``/hidp.py`` = ``hid_peripheral.py``, and
  ``/hidp_plant.py`` = the same with ``PLANT = True``;
* the P4: ``/hidc.py`` = ``hid_central.py``, and ``/hidc_fast.py`` = the same
  with ``FAST = True`` (a 7.5-15 ms interval);
* ``hid_script.mpy`` in both boards' ``/lib``.

Then::

    python.exe p4_hid_gate.py --p4 COM4 --dev COM17 --mode default --runs 10 --log hid.log

Each run soft-resets the device and starts it, hard-resets the P4 (BLE can't
start twice after a soft reset there, micropython-pydevices#13), then starts
the host at the friendly prompt, where ESP-IDF's log still reaches the UART:
every ``alloc_acl_from_ll failed`` (a packet ESP-Hosted dropped) is counted.
``--mode plant`` runs the planted device, which must FAIL. A run whose host
never connects is counted as a connect failure and not as a gate result.

``--mode connect`` measures connects instead: the device runs
``connect_loop_server.py`` and the P4 ``connect_loop_client.py`` (both at
``/``), ten connects per hard reset. ``--wifi-off`` turns the P4's Wi-Fi
station off after each boot, for a board whose boot.py joins a network.
"""
import re
import sys
import time

from uart_rig import Board, wait


WIFI_OFF = "--wifi-off" in sys.argv  # turn the P4's station off after boot.py joins it


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def connects(p4, dev):
    r = {"mode": "connect"}
    if not dev.soft_reset():
        r["error"] = "device: no prompt after soft reset"
        return r
    dev.mark()
    dev.line("import connect_loop_server")
    time.sleep(2)
    if not p4.hard_reset():
        r["error"] = "P4: no prompt after hard reset"
        return r
    if WIFI_OFF:
        p4.say("import network; network.WLAN(network.STA_IF).active(False)")
    p4.mark()
    p4.line("import connect_loop_client")
    wait([p4, dev], lambda: (b"CONNECTS" in p4.buf or b"Traceback" in p4.buf) and p4.buf.rstrip().endswith(b">>>"), 600)
    host = p4.text()
    r["drops"] = host.count("alloc_acl_from_ll failed")
    m = re.search(r"CONNECTS (\d+) ok (\d+) timeouts (\d+) other (\d+) not found (\d+) times (.*)", host)
    if m:
        r.update(attempts=int(m.group(1)), ok=int(m.group(2)), timeouts=int(m.group(3)), other=int(m.group(4)),
                 missing=int(m.group(5)), times=m.group(6).strip())
    else:
        r["error"] = "no CONNECTS line"
    r["accepted"] = dev.text().count("accepted")
    return r


def one(p4, dev, mode):
    if mode == "connect":
        return connects(p4, dev)
    r = {"mode": mode}
    if not dev.soft_reset():
        r["error"] = "device: no prompt after soft reset"
        return r
    dev.mark()
    dev.line("import hidp_plant" if mode == "plant" else "import hidp")
    if not wait([dev], lambda: b"advertising as" in dev.buf, 20):
        r["error"] = "device never advertised"
        return r
    if not p4.hard_reset():
        r["error"] = "P4: no prompt after hard reset"
        return r
    if WIFI_OFF:
        p4.say("import network; network.WLAN(network.STA_IF).active(False)")
    p4.mark()
    p4.line("import hidc_fast" if mode == "fast" else "import hidc")
    finished = lambda: (b"RESULT " in p4.buf or b"Traceback" in p4.buf) and p4.buf.rstrip().endswith(b">>>")
    ok = wait([p4, dev], finished, 180)
    wait([p4, dev], lambda: b"DONE" in dev.buf, 10 if b"RESULT" in p4.buf else 0)
    host, device = p4.text(), dev.text()
    r["drops"] = host.count("alloc_acl_from_ll failed")
    m = re.search(r"connected and started in (\d+) ms", host)
    r["connect_ms"] = int(m.group(1)) if m else None
    m = re.search(r"events (\d+) want (\d+)", host)
    r["events"] = "{}/{}".format(m.group(1), m.group(2)) if m else None
    m = re.search(r"MISMATCH (.*)", host)
    r["mismatch"] = m.group(1)[:100] if m else None
    m = re.search(r"RESULT (\w+)", host)
    r["result"] = m.group(1) if m else None
    m = re.search(r"latency phase stalled after (\d+)", host)
    r["stalled_after"] = int(m.group(1)) if m else None
    m = re.search(r"round trip, press to the host's LED write: (.*)", device)
    r["rtt"] = m.group(1).strip() if m else None
    if "Traceback" in host:
        tb = host[host.index("Traceback"):].strip().split("\n")
        r["exception"] = tb[-2] if tb[-1].startswith(">>>") else tb[-1]
        r["connect_timeout"] = r["connect_ms"] is None and "Timeout" in r["exception"] and "no device matching" not in r["exception"]
    if not ok:
        r["error"] = "host didn't finish in 180 s"
    return r


def main():
    mode = arg("--mode", "default")
    runs = int(arg("--runs", "1"))
    log = open(arg("--log", "p4_hid_gate.log"), "a", encoding="utf-8")
    p4 = Board(arg("--p4", "COM4"), "P4", log)
    dev = Board(arg("--dev", "COM17"), "DEV", log)
    results = []
    for i in range(runs):
        log.write("==== run {} mode {} {}\n".format(i + 1, mode, time.strftime("%H:%M:%S")))
        r = one(p4, dev, mode)
        results.append(r)
        print("run", i + 1, r, flush=True)
    dev.prompt()
    p4.hard_reset()
    if mode == "connect":
        print("SUMMARY connect sessions", len(results), "attempts", sum(r.get("attempts", 0) for r in results),
              "ok", sum(r.get("ok", 0) for r in results), "timeouts", sum(r.get("timeouts", 0) for r in results),
              "other", sum(r.get("other", 0) for r in results), "not found", sum(r.get("missing", 0) for r in results),
              "drops", sum(r.get("drops") or 0 for r in results))
        return
    done = [r for r in results if r.get("result")]
    print("SUMMARY mode", mode, "runs", len(results), "completed", len(done),
          "PASS", sum(r["result"] == "PASS" for r in done),
          "with drops", sum(bool(r.get("drops")) for r in results),
          "drops total", sum(r.get("drops") or 0 for r in results),
          "connect timeouts", sum(bool(r.get("connect_timeout")) for r in results))


main()
