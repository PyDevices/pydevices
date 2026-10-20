# The frozen Python for the CircuitPython interpreter attached to a release.
#
# release_interpreters.sh passes this file to make through build_mp.py
# --interpreter circuitpython (FROZEN_MANIFEST). CircuitPython's manifest tool
# has no c_module(): our C reaches it through USER_C_MODULES, so this file
# names only Python.
#
# RELEASE_INTERPRETERS_WS is a directory holding checkouts of
# lvgl-circuitpython, pdwidgets and palettes.
import os

_ws = os.environ["RELEASE_INTERPRETERS_WS"]

# The port's own freeze for the variant being built, first.
include("$(PORT_DIR)/variants/coverage/manifest.py")

# lvgl on CircuitPython: fs_driver. display_driver comes with pydevices.
include(os.path.join(_ws, "lvgl-circuitpython", "manifest.py"))

# The widget library and the palettes, both pure Python.
include(os.path.join(_ws, "pdwidgets", "manifest.py"))
include(os.path.join(_ws, "palettes", "manifest.py"))
