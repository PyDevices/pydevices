# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# appkit's MicroPython manifest. From a board's manifest.py:
#
#   include("/path/to/appkit")                    appkit alone
#
#   import os
#   include("/path/to/appkit", apps=os.path.abspath("apps"))
#                                                 appkit, every app in apps/,
#                                                 and their index, _appkit_apps
#
# apps= must be an absolute path: this file runs from appkit's own folder.
# index_dir= says where to write _appkit_apps.py (default: a temporary folder).

options.defaults(apps=None, index_dir=None)

package("appkit", base_path="lib")

if options.apps:
    import importlib.util
    import os

    if not os.path.isabs(options.apps):
        raise ValueError("appkit manifest: apps=%r must be an absolute path" % (options.apps,))
    spec = importlib.util.spec_from_file_location("appkit_index", os.path.abspath("lib/appkit/index.py"))
    index = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(index)
    index.freeze_apps(options.apps, module, package, options.index_dir)
