# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""scan(), script entries and the generated index.

``scripts_contract.py`` holds the in-process checks; this file runs them on
CPython and unix MicroPython, with each planted fault. Then the whole round
trip through real restarts, on the sample app set in ``sample_set/``: the
home screen comes up, the autopilot taps "Blocks" (a plain script), the
program restarts into it, the script plays on its timer and quits, and the
program restarts to the home screen again. On MicroPython that runs under
``python -m appkit.launcher``; on CPython the restarts are ``os.execv``. The
frozen-style run does the same from a folder with no ``apps/`` in it, with
the apps and their generated index on the module path as a frozen build
has them. Last, the index generator itself, and appkit's manifest through
MicroPython's own manifest reader when a MicroPython checkout is found.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _harness import LIB, PYDEVICES_LIB, TESTS, ContractCase, need_micropython, run

sys.path.insert(0, str(LIB))
if PYDEVICES_LIB is not None:
    sys.path.insert(1, str(PYDEVICES_LIB))
from appkit import index  # noqa: E402  (runs without the rest of appkit)

CONTRACT = "scripts_contract.py"
SET = TESTS / "sample_set"
SUPERVISE = [sys.executable, "-m", "appkit.launcher", "--"]

PLANTS = (
    "script-early",
    "index-ignored",
    "script-as-app",
    "pending-taken",
    "no-close",
    "boot-runs-script",
    "bare-import",
    "parent-kept",
    "init-unmade",
    "init-silent",
)

#: What a good round trip logs, in order.
ROUND_TRIP = [
    "HOME 1 current=home names=blocks,hello,home",
    "LOOP True",
    "TAP Blocks",
    "SCRIPT start",
    "SCRIPT body done",
    "SCRIPT quit after 15 ticks",
    "HOME 2 current=home names=blocks,hello,home",
    "LOOP True",
    "DONE",
]


def _board_configs():
    if PYDEVICES_LIB is None:
        return None
    path = PYDEVICES_LIB.parent / "board_configs" / "desktop"
    return path if path.is_dir() else None


class ScriptsContract(ContractCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        index.write(str(SET / "apps"), self.tmp.name)
        self.env = {"APPKIT_TEST_INDEX": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def test_cpython(self):
        self.assertPasses(run([sys.executable, CONTRACT], extra_env=self.env))

    def test_micropython(self):
        mp = need_micropython(self)
        self.assertPasses(run([mp, CONTRACT], extra_env=self.env))

    def _plants(self, cmd):
        for plant in PLANTS:
            with self.subTest(plant=plant):
                result = run(cmd + ["--plant=" + plant], extra_env=self.env)
                self.assertIn("PLANTED " + plant, result.stdout, result.stdout + result.stderr)
                self.assertFailsWith(result, "FAIL ")
                self.assertIn(" 1 failed", result.stdout, result.stdout)

    def test_planted_cpython(self):
        self._plants([sys.executable, CONTRACT])

    def test_planted_micropython(self):
        self._plants([need_micropython(self), CONTRACT])


class RoundTrip(ContractCase):
    """Home, a script, the script quits, home again: real restarts."""

    def setUp(self):
        if _board_configs() is None:
            self.skipTest("no pydevices board_configs/desktop: the round trip needs a display")
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, cmd, cwd=SET, extra=None, plant=None):
        env = {"APPKIT_DATA": os.path.join(self.tmp.name, "data")}
        env.update(extra or {})
        if plant:
            env["APPKIT_PLANT"] = plant
        # board_config for the desktop, and the desktop helpers it imports
        # (usdl2 and the rest, in utils/), after pydevices' lib.
        configs = os.pathsep.join((str(PYDEVICES_LIB.parent / "utils"), str(_board_configs())))
        mp_path = os.pathsep.join(p for p in (env.pop("FROZEN", None), str(LIB), str(PYDEVICES_LIB), configs) if p)
        env["MICROPYPATH"] = mp_path.replace(os.pathsep, ":") + ":.frozen"
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (env.pop("FROZEN_PY", None), str(LIB), str(PYDEVICES_LIB), configs) if p
        )
        try:
            result = run(cmd, state_dir=self.tmp.name, extra_env=env, cwd=cwd, timeout=90)
        except subprocess.TimeoutExpired as exc:
            result = None
            self.timed_out = exc
        log = os.path.join(self.tmp.name, "log.txt")
        lines = []
        if os.path.exists(log):
            with open(log) as f:
                lines = f.read().splitlines()
            os.remove(log)
        return result, lines

    def assertRoundTrip(self, result, lines):
        self.assertIsNotNone(result, "timed out; the log: %r" % (lines,))
        out = result.stdout + result.stderr
        self.assertEqual(lines, ROUND_TRIP, out)
        self.assertEqual(result.returncode, 0, out)

    def test_micropython_supervised(self):
        mp = need_micropython(self)
        self.assertRoundTrip(*self._run(SUPERVISE + [mp, "main.py"]))

    def test_micropython_supervised_without_the_loop(self):
        # A program that doesn't end in appkit.serve(): the restarts go
        # through the interpreter's exit hook, and the restart file.
        mp = need_micropython(self)
        result, lines = self._run(SUPERVISE + [mp, "main.py"], extra={"APPKIT_NO_LOOP": "1"})
        self.assertEqual(lines.count("NO LOOP"), 3, lines)
        self.assertEqual(lines.count("LOOP False"), 2, lines)
        lines = [line.replace("LOOP False", "LOOP True") for line in lines if line != "NO LOOP"]
        self.assertRoundTrip(result, lines)

    def test_cpython_execv(self):
        self.assertRoundTrip(*self._run([sys.executable, "main.py"]))

    def test_planted_micropython(self):
        mp = need_micropython(self)
        for plant in ("no-pending-check", "script-early", "no-restart-file"):
            with self.subTest(plant=plant):
                result, lines = self._run(SUPERVISE + [mp, "main.py"], plant=plant)
                self.assertIn("PLANTED " + plant, lines[:1], lines)
                trip = [line for line in lines if not line.startswith("PLANTED")]
                self.assertNotEqual(trip, ROUND_TRIP, "a planted fault went unnoticed")
                if plant == "script-early":
                    self.assertNotIn("SCRIPT quit after 15 ticks", lines)

    def _frozen(self, mp):
        """A folder with no apps/, and the apps and index where a frozen build has them."""
        work = os.path.join(self.tmp.name, "board")
        frozen = os.path.join(self.tmp.name, "frozen")
        os.makedirs(work)
        os.makedirs(frozen)
        for name in ("main.py", "autopilot.py"):
            shutil.copy(str(SET / name), work)

        def module(path, base_path="."):
            os.makedirs(os.path.dirname(os.path.join(frozen, path)), exist_ok=True)
            shutil.copy(os.path.join(base_path, path), os.path.join(frozen, path))

        def package(path, base_path="."):
            shutil.copytree(os.path.join(base_path, path), os.path.join(frozen, path))

        index.freeze_apps(str(SET / "apps"), module, package, os.path.join(self.tmp.name, "index"))
        self.assertEqual(sorted(os.listdir(frozen)), ["_appkit_apps.py", "apps", "blocks.py"])
        self.assertEqual(sorted(os.listdir(os.path.join(frozen, "apps"))), ["__init__.py", "hello"])
        return work, frozen

    def test_micropython_frozen(self):
        mp = need_micropython(self)
        work, frozen = self._frozen(mp)
        self.assertRoundTrip(*self._run(SUPERVISE + [mp, "main.py"], cwd=work, extra={"FROZEN": frozen}))
        result, lines = self._run(
            SUPERVISE + [mp, "main.py"], cwd=work, extra={"FROZEN": frozen}, plant="index-ignored"
        )
        self.assertIsNotNone(result, "the planted run hung; the log: %r" % (lines,))
        self.assertIn("CRASH OSError: no apps: there is no folder 'apps' and no _appkit_apps module", lines, lines)
        self.assertNotIn("HOME 1 current=home names=blocks,hello,home", lines, "a planted fault went unnoticed")

    def test_cpython_frozen(self):
        work, frozen = self._frozen(None)
        self.assertRoundTrip(*self._run([sys.executable, "main.py"], cwd=work, extra={"FROZEN_PY": frozen}))


class Index(unittest.TestCase):
    def test_collect_and_render(self):
        apps = index.collect(str(SET / "apps"))
        self.assertEqual([entry for entry, info in apps], ["blocks", "hello"])
        ns = {}
        exec(index.render(apps), ns)
        self.assertEqual(ns["APPS"], (("blocks", apps[0][1]), ("hello", apps[1][1])))
        self.assertEqual(ns["APPS"][0][1]["script"], "blocks")

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.py")
            result = subprocess.run(
                [sys.executable, str(LIB / "appkit" / "index.py"), str(SET / "apps"), "-o", out],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(out) as f:
                self.assertIn("('hello', {'name': 'hello', 'title': 'Hello'})", f.read())
            result = subprocess.run([sys.executable, str(LIB / "appkit" / "index.py")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("usage", result.stdout)

    def test_bad_app_json_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "bad"))
            with open(os.path.join(tmp, "bad", "app.json"), "w") as f:
                f.write("{not json")
            with self.assertRaises(ValueError) as cm:
                index.collect(tmp)
            self.assertIn("bad", str(cm.exception))

    def test_manifest_through_micropythons_reader(self):
        # appkit's manifest.py as a firmware build reads it.
        found = None
        for parent in TESTS.parents:
            candidate = parent / "micropython" / "tools" / "manifestfile.py"
            if candidate.is_file():
                found = candidate
                break
        found = os.environ.get("MICROPYTHON_MANIFESTFILE", found)
        if not found:
            self.skipTest("no MicroPython checkout with tools/manifestfile.py")
        with tempfile.TemporaryDirectory() as tmp:
            board = os.path.join(tmp, "manifest.py")
            with open(board, "w") as f:
                f.write(
                    "import os\ninclude(%r, apps=%r, index_dir=%r)\n"
                    % (str(TESTS.parent), str(SET / "apps"), os.path.join(tmp, "index"))
                )
            result = subprocess.run(
                [sys.executable, str(found), "--freeze", board], capture_output=True, text=True, cwd=tmp
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            listed = result.stdout
            for frozen_as in (
                "_appkit_apps.py",
                "blocks.py",
                "apps/__init__.py",
                "apps/hello/__init__.py",
                "appkit/launcher.py",
            ):
                self.assertIn(frozen_as, listed, listed)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "index", "_appkit_apps.py")))


if __name__ == "__main__":
    unittest.main()
