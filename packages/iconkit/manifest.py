# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Freeze the iconkit package from its canonical source tree.

Both icon sets are frozen, so the masks stay in flash: the 24 px set is 72 KB
and the 48 px set another 72 KB. A firmware build includes this file from its
own freeze manifest, as it does for palettes.
"""

if 0:

    def package(*args, **kwargs):
        pass

    def module(*args, **kwargs):
        pass


package("iconkit", base_path="./lib", opt=3)  # type: ignore[name-defined]  # noqa: PGH003
