# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Tests for the cross-interpreter env helpers in ``boarddev``."""

import os
import unittest

import _env  # noqa: F401

import boarddev


class TestEnvBool(unittest.TestCase):
    def test_missing_returns_default(self):
        os.environ.pop("PYDEVICES_TEST_ENV_BOOL", None)
        boarddev._overrides.pop("PYDEVICES_TEST_ENV_BOOL", None)
        self.assertFalse(boarddev.env_bool("PYDEVICES_TEST_ENV_BOOL", False))
        self.assertTrue(boarddev.env_bool("PYDEVICES_TEST_ENV_BOOL", True))

    def test_truthy_values(self):
        for value in ("1", "true", "TRUE", " yes ", "on"):
            os.environ["PYDEVICES_TEST_ENV_BOOL"] = value
            self.assertTrue(boarddev.env_bool("PYDEVICES_TEST_ENV_BOOL", False))

    def test_falsey_values(self):
        for value in ("0", "false", "NO", " off "):
            os.environ["PYDEVICES_TEST_ENV_BOOL"] = value
            self.assertFalse(boarddev.env_bool("PYDEVICES_TEST_ENV_BOOL", True))

    def test_unknown_value_uses_default(self):
        os.environ["PYDEVICES_TEST_ENV_BOOL"] = "maybe"
        self.assertFalse(boarddev.env_bool("PYDEVICES_TEST_ENV_BOOL", False))
        self.assertTrue(boarddev.env_bool("PYDEVICES_TEST_ENV_BOOL", True))

    def test_env_set_override_without_os_environ(self):
        boarddev._overrides.pop("PYDEVICES_TEST_ENV_SET", None)
        os.environ.pop("PYDEVICES_TEST_ENV_SET", None)
        boarddev.env_set("PYDEVICES_TEST_ENV_SET", "1")
        self.assertTrue(boarddev.env_bool("PYDEVICES_TEST_ENV_SET", False))
        boarddev.env_set("PYDEVICES_TEST_ENV_SET", "0")
        self.assertFalse(boarddev.env_bool("PYDEVICES_TEST_ENV_SET", True))

    def test_env_float(self):
        boarddev.env_set("PYDEVICES_TEST_ENV_FLOAT", "1.25")
        self.assertEqual(boarddev.env_float("PYDEVICES_TEST_ENV_FLOAT", 2), 1.25)
        boarddev.env_set("PYDEVICES_TEST_ENV_FLOAT", "invalid")
        self.assertEqual(boarddev.env_float("PYDEVICES_TEST_ENV_FLOAT", 2), 2.0)

    def tearDown(self):
        os.environ.pop("PYDEVICES_TEST_ENV_BOOL", None)
        os.environ.pop("PYDEVICES_TEST_ENV_SET", None)
        boarddev._overrides.pop("PYDEVICES_TEST_ENV_BOOL", None)
        boarddev._overrides.pop("PYDEVICES_TEST_ENV_FLOAT", None)
        boarddev._overrides.pop("PYDEVICES_TEST_ENV_SET", None)


class TestTheyLeftDisplaydev(unittest.TestCase):
    """A hard break: the helpers moved to boarddev and displaydev keeps none."""

    NAMES = ("env_get", "env_int", "env_float", "env_bool", "env_set", "_env_raw", "_overrides")

    def test_from_displaydev_import_fails(self):
        import displaydev

        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertFalse(hasattr(displaydev, name))
                self.assertNotIn(name, displaydev.__all__)
                with self.assertRaises(ImportError):
                    exec("from displaydev import " + name, {})

    def test_displaydev_still_reads_them_through_boarddev(self):
        """displaydev reads PYDEVICES_* through boarddev at call time."""
        import inspect

        import displaydev

        source = inspect.getsource(displaydev)
        self.assertIn("from boarddev import env_bool, env_float", source)
        self.assertIn("from boarddev import env_int", source)


if __name__ == "__main__":
    unittest.main()
