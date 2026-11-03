# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Sphinx configuration for the palettes documentation.

Everything shared by the PyDevices documentation projects (theme, top bar,
Markdown and docstring setup, the reference map) comes from pydevices-docs.
"""

from pydevices_docs import configure

globals().update(configure(
    "palettes", __file__,
    repo="PyDevices/pydevices", edit_path="packages/palettes/docs",
    source_dirs=["../lib"], api_packages=["palettes"],
    version_file="../VERSION",
))
