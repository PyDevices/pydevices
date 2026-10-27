"""Sphinx configuration for the pydevices documentation.

Everything shared by the PyDevices documentation projects (theme, top bar,
Markdown and docstring setup, the reference map) comes from pydevices-docs.
"""

from pydevices_docs import configure

globals().update(configure(
    "pydevices", __file__,
    repo="PyDevices/pydevices", edit_path="docs",
    source_dirs=["../lib", "../utils"],
    api_packages=["displaydev", "audiodev", "appdev", "multimer", "bledev"],
    mock_imports=["bleak", "_bleio", "bluetooth", "IPython", "pygame", "js",
                  "pyodide", "_wasm_bridge", "uwin32", "aioble", "PIL", "lvgl"],
    # windisplay builds window styles from uwin32 constants at import time,
    # which a mock cannot stand in for.
    api_skip=["windisplay"],
    version_file="../VERSION",
))

# index.md is plain Markdown so the docs read on GitHub too; the site
# navigation lives in contents.md.
master_doc = "contents"
