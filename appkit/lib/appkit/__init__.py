# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appkit: apps you can switch between, and a launcher to run them.

::

    import appkit
    appkit.run()            # a home screen of every app in ./apps
    appkit.run("hello")     # one app, alone
"""

from .foreground import serve
from .launcher import Launcher, host, run_pending_script
from .scope import AppScope
from .shell import Shell


def run(name=None, folder="apps", *, data_root=None):
    """Run the apps in *folder*: a home screen listing them, or app *name* alone.

    It ends in the main-thread loop, :func:`serve`, and returns the
    ``Launcher`` when the program quits. In a browser, where the page has
    the main thread, it returns the launcher at once. *data_root* moves
    every app's ``data_dir`` and the launcher's restart file (see
    ``appkit.data``). A plain script the home screen started runs here
    first, before the display opens, and doesn't return.
    """
    if run_pending_script(data_root):
        return None  # a browser, reloading
    from display_driver import app  # the one App every LVGL program shares

    launcher = Launcher(app)
    launcher.scan(folder)
    if name is None:
        launcher.add("home", "appkit.home")
        launcher.home = "home"
    launcher.shell = Shell(launcher)
    launcher.boot(name)
    if host() != "browser":
        serve(app)
    return launcher
