# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""What a person would do at the sample set's home screen, and a log of it.

The first time the home screen comes up it taps "Blocks", a plain script.
The script plays itself and quits; the program must then come back to the
home screen, and the second time it does, the autopilot quits. Each line it
logs goes to ``$APPKIT_TEST_DIR/log.txt``, which outlives the restarts.
"""

import os
import sys


def log(line):
    with open(os.getenv("APPKIT_TEST_DIR") + "/log.txt", "a") as f:
        f.write(line + "\n")


def _homes():
    try:
        with open(os.getenv("APPKIT_TEST_DIR") + "/log.txt") as f:
            return sum(1 for line in f.read().split("\n") if line.startswith("HOME"))
    except OSError:
        return 0


def _no_loop():
    # run() returns at once, as a program that doesn't end in appkit.serve()
    # does: the interpreter's exit hook runs the timers from then on.
    import appkit

    appkit.serve = lambda app=None: None


def plant():
    """Break appkit in the way ``APPKIT_PLANT`` names, before it runs.

    ``APPKIT_NO_LOOP=1`` isn't a fault: it runs the program without the
    foreground loop, as an app set that ends without one does.
    """
    if os.getenv("APPKIT_NO_LOOP"):
        log("NO LOOP")
        _no_loop()
    name = os.getenv("APPKIT_PLANT")
    if not name:
        return
    log("PLANTED " + name)
    import appkit
    from appkit import launcher as L

    if name == "no-pending-check":
        # run() no longer runs a pending script first.
        appkit.run_pending_script = lambda data_root=None: False
    elif name == "script-early":
        # The launcher goes home as soon as the script's import returns.
        L._app_done = lambda app: True
    elif name == "no-restart-file":
        # A restart from a callback leaves no file for the supervisor, so only
        # the exit code says to restart.
        # Inside the foreground loop the exit code always gets out, so this
        # one only shows without it.
        from appkit import data

        _no_loop()
        getenv = data._getenv
        data._getenv = lambda var: None if var == "APPKIT_RESTART_FILE" else getenv(var)
    elif name == "index-ignored":
        # scan() never reads the generated index.
        imp = L._import

        def no_index(module):
            if module == "_appkit_apps":
                raise ImportError(module)
            return imp(module)

        L._import = no_index
    else:
        raise ValueError("no plant named %r" % (name,))


def crash(exc):
    """Log *exc* and end the program, which its App's timers would otherwise
    keep alive."""
    log("CRASH %s: %s" % (type(exc).__name__, exc))
    import multimer
    from appdev import App

    app = App.current()
    if app is not None:
        app.request_quit()
    multimer.stop_all()
    multimer.keepalive(False)
    sys.exit(1)


def _button(lv, page, text):
    for i in range(page.get_child_count()):
        b = page.get_child(i)
        if b.get_child_count() and b.get_child(0).get_text() == text:
            return b
    return None


def watch():
    """Wait for the launcher ``appkit.run()`` makes, then :func:`drive` it.

    ``run()`` doesn't return until the program quits, so the autopilot
    finds the launcher through the scope of the app it started.
    """
    import multimer
    from appkit.scope import open_scopes

    def look(timer):
        for scope in open_scopes():
            if scope.launcher is not None and scope.launcher.scope is scope:
                timer.deinit()
                drive(scope.launcher)
                return

    multimer.every(20, look, name="autopilot.watch")


def drive(launcher):
    import lvgl as lv

    from appkit import foreground

    homes = _homes() + 1
    log("HOME %d current=%s names=%s" % (homes, launcher.current, ",".join(launcher.names)))
    app = launcher.app

    def tap(timer):
        # By now run() has reached its loop, unless it doesn't have one.
        log("LOOP %s" % (foreground.serving(),))
        if homes == 1:
            b = _button(lv, launcher.scope.root, "Blocks")
            log("TAP Blocks" if b is not None else "NO BUTTON")
            if b is not None:
                b.send_event(lv.EVENT.CLICKED, None)
        else:
            log("DONE")
            app.request_quit()

    launcher.scope.after(300, tap)
