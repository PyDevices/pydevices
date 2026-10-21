"""Sphinx configuration for the pdwidgets documentation.

Everything shared by the PyDevices documentation projects (theme, top bar,
Markdown and docstring setup, the reference map) comes from pydevices-docs.
"""

from pydevices_docs import configure

globals().update(configure(
    "pdwidgets", __file__,
    repo="PyDevices/pydevices", edit_path="pdwidgets/docs",
    # palettes sits beside pdwidgets in this repository and is a real
    # dependency; pygraphics and the rest of the stack are mocked below.
    source_dirs=["../lib", "../../palettes/lib"],
    api_packages=["pdwidgets"],
    api_skip=["icons"],
    mock_imports=["pygraphics", "events", "appdev", "board_config", "displaydev", "multimer", "keys", "micropython", "framebuf"],
    version_file="../VERSION",
))
