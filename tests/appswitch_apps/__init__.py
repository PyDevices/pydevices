# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Sample switchable apps for the appdev scope and launcher tests.

``clock`` and ``counter`` are well-behaved. ``leaky`` parks a callback in a
shared module's global, ``hoarder`` parks plain data there, and ``badclose``
has an ``on_close`` hook that raises: the tests use those to prove their
checks can fail. ``shared`` is the shared module they park things in; it is
not part of any app, so closing an app leaves it loaded.
"""
