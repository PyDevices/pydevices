#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Thorough PyScript debug runner — captures all JS console output via CDP,
monitors #log div for Python print() output, tracks network requests,
and checks for WASM loading errors.

Prefer this over browser screenshots when sync Python may be blocking
the main thread (page.evaluate / screenshots often hang).

Usage:
    python tools/ps_debug.py URL [timeout_sec]
"""

import json
import os
import sys
import time

from playwright.sync_api import TimeoutError as PwTimeout
from playwright.sync_api import sync_playwright

URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else ("http://127.0.0.1:8000/pydevices-examples/pyscript/harness.html?modules=bouncing_balls&debug=1")
)
TIMEOUT_SEC = int(sys.argv[2]) if len(sys.argv) > 2 else 25

t0 = time.time()
all_events = []
TEMP_DIR = os.environ.get("TEMP") or os.environ.get("TMPDIR") or os.environ.get("TMP") or "/tmp"
DEBUG_SHOT = f"{TEMP_DIR.rstrip('/')}/pyscript_debug.png"


def ts():
    return f"{time.time() - t0:6.1f}s"


def run():
    print(f"[{ts()}] Launching Chromium (CDP verbose debug)...", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--enable-logging=stderr",
                "--v=1",
            ],
        )
        ctx = browser.new_context()
        page = ctx.new_page()

        # Connect directly to Chrome DevTools Protocol session
        cdp = ctx.new_cdp_session(page)

        # 1. Enable console events
        cdp.send("Console.enable")
        cdp.send("Runtime.enable")

        def on_console_msg(params):
            msg = params.get("message", {})
            lvl = msg.get("level", "?")
            txt = msg.get("text", "")
            url = msg.get("url", "")
            line = msg.get("line", "")
            src = f" ({os.path.basename(url)}:{line})" if url else ""
            print(f"[{ts()}][CDP-CONSOLE {lvl.upper()}]{src} {txt}", flush=True)

        def on_runtime_console(params):
            typ = params.get("type", "?")
            args = params.get("args", [])
            vals = []
            for a in args:
                v = a.get("value")
                if v is not None:
                    vals.append(str(v))
                elif "description" in a:
                    vals.append(a["description"])
                else:
                    vals.append(repr(a))
            txt = " ".join(vals)
            print(f"[{ts()}][CONSOLE {typ.upper()}] {txt}", flush=True)

        def on_exception(params):
            exc = params.get("exceptionDetails", {})
            txt = exc.get("text", "")
            ex = exc.get("exception", {})
            desc = ex.get("description", "")
            print(f"[{ts()}][EXCEPTION] {txt}\n  {desc}", flush=True)

        cdp.on("Console.messageAdded", on_console_msg)
        cdp.on("Runtime.consoleAPICalled", on_runtime_console)
        cdp.on("Runtime.exceptionThrown", on_exception)

        # 2. Monitor Network
        cdp.send("Network.enable")

        def on_req_failed(params):
            url = params.get("request", {}).get("url", params.get("requestId", ""))
            err = params.get("errorText", "")
            cancelled = params.get("canceled", False)
            if not cancelled:
                print(f"[{ts()}][NET FAIL] {err} -> {url}", flush=True)

        def on_resp(params):
            resp = params.get("response", {})
            status = resp.get("status", 0)
            url = resp.get("url", "")
            if status >= 400:
                print(f"[{ts()}][HTTP {status}] {url}", flush=True)

        cdp.on("Network.loadingFailed", on_req_failed)
        cdp.on("Network.responseReceived", on_resp)

        # 3. Standard Playwright console / pageerror hooks
        page.on("pageerror", lambda e: print(f"[{ts()}][PAGEERROR] {e}", flush=True))

        print(f"[{ts()}] Navigating to: {URL}", flush=True)
        try:
            page.goto(URL, timeout=TIMEOUT_SEC * 1000, wait_until="domcontentloaded")
            print(f"[{ts()}] domcontentloaded fired", flush=True)
        except PwTimeout:
            print(f"[{ts()}][TIMEOUT] page.goto() timed out at {TIMEOUT_SEC}s", flush=True)
        except Exception as e:
            print(f"[{ts()}][ERROR] page.goto() threw: {e}", flush=True)

        # 4. Wait loop checking #log div
        print(f"[{ts()}] Monitoring for up to {TIMEOUT_SEC}s total...", flush=True)
        last_log_text = ""
        while time.time() - t0 < TIMEOUT_SEC:
            time.sleep(1.0)
            try:
                log_el = page.query_selector("#log")
                if log_el:
                    cur = log_el.inner_text().strip()
                    if cur and cur != last_log_text:
                        new_lines = cur[len(last_log_text):].strip()
                        if new_lines:
                            print(f"[{ts()}][#LOG]\n{new_lines}", flush=True)
                        last_log_text = cur
            except Exception:
                pass

        # 5. Take screenshot
        try:
            page.screenshot(path=DEBUG_SHOT, timeout=5000)
            print(f"[{ts()}] Saved debug screenshot to {DEBUG_SHOT}", flush=True)
        except Exception as e:
            print(f"[{ts()}][SCREENSHOT FAIL] {e}", flush=True)

        browser.close()
        print(f"[{ts()}] Done.", flush=True)


if __name__ == "__main__":
    run()
