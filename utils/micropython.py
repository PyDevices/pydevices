# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
micropython.py - A module to prevent errors when running applications
written for both CPython and MicroPython.  Doesn't (necessarily) allow
the functions to run, but prevents them from throwing errors when loaded.
"""

const = viper = native = lambda x: x
