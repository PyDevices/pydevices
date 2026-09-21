# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run ``tests/pump_probes/`` under a real interpreter that has the pump.

``tests/test_pump.py`` proves the arbitration with stand-ins. This is the
other half: the real ``audiopump`` engine on its own thread, pulling a real
``audiocore`` graph, recorded through ``audiodev.emulated_audio`` -- which is
the only way to say that the pump path is *byte-identical* to the old one, or
that a hundred play/stop rounds leave nothing behind.

It needs an interpreter CPython cannot stand in for: a MicroPython or
CircuitPython build carrying the ``audioif`` usermod **and** the
``audiopump`` driver. Point one out with ``PYDEVICES_PUMP_INTERPRETER``, or
put it on PATH as ``micropython``.

**A skip here is loud on purpose.** No runner in this repository's CI has
such a binary today, so without the banner below this file would report
nothing at all, for ever, and read as coverage. It prints what it did not
run and why, and ``PYDEVICES_REQUIRE_PUMP=1`` turns the skip into a failure
-- which is what a CI job that *does* build an interpreter must set.
"""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

PROBES = _TESTS / "pump_probes"
ROOT = _env.ROOT

#: Names tried on PATH when PYDEVICES_PUMP_INTERPRETER says nothing.
CANDIDATES = ("micropython", "micropython.exe", "circuitpython")

#: Every probe run, as (name, arguments, the faults it must fail on).
#:
#: A fault that passes is a probe that proves nothing, so each one is run
#: first and has to come back non-zero. They are the spike's own, named in
#: each probe's header.
RUNS = (
    ("lifecycle", ["lifecycle.py"], ("silent", "leak", "short")),
    # `chain` wants audioeffects, which this package does not depend on.
    ("identity", ["identity.py", "raw", "synth", "wav"],
     ("drop", "flip", "short")),
)

#: Faults that need the pump on a thread of its own.
#:
#: `drop` used to be one. It planted a free-running pump, which only drops on
#: a build that HAS a second thread -- so on a driverless one the plant quietly
#: passed and had to be left out. It does not plant that any more, because a
#: free-running pump is now the healthy shape: the output ring blocks it. It
#: shrinks the output ring below one block of the graph instead, which is the
#: one loss no wait can prevent, and that lands on both builds.
THREADED_ONLY = ()

#: What the probes could not be run against, filled in by the finder so the
#: banner can say it once rather than once per test.
_MISSED = []


#: Whether the interpreter found puts the pump on a thread of its own.
_THREADED = []


def _interpreter():
    """(path, why-not). Exactly one of the two is None."""
    named = os.getenv("PYDEVICES_PUMP_INTERPRETER")
    if named:
        if not Path(named).exists():
            return None, "PYDEVICES_PUMP_INTERPRETER=%s does not exist" % named
        found = named
    else:
        found = next((shutil.which(name) for name in CANDIDATES
                      if shutil.which(name)), None)
        if found is None:
            return None, ("no %s on PATH and PYDEVICES_PUMP_INTERPRETER is "
                          "unset" % "/".join(CANDIDATES))
    probe = ("import audiopump, audiocore\n"
             "print('pump' if hasattr(audiopump, 'spawn') else 'no',\n"
             "      'threaded' if audiopump.threaded() else 'service')\n")
    try:
        result = subprocess.run([found, "-c", probe], capture_output=True,
                                text=True, timeout=60)
    except OSError as exc:
        return None, "%s would not run (%s)" % (found, exc)
    if result.returncode != 0 or "pump" not in result.stdout:
        return None, ("%s has no usable audiopump: %s"
                      % (found, (result.stderr or result.stdout).strip()
                         .splitlines()[-1:] or "no spawn"))
    _THREADED.append("threaded" in result.stdout)
    return found, None


def _run(interpreter, arguments, tmpdir):
    env = dict(os.environ)
    env["PUMP_PROBE_TMP"] = tmpdir
    path = [str(ROOT / "lib")]
    for name in ("MICROPYPATH", "PYTHONPATH"):
        if env.get(name):
            path.append(env[name])
    # MicroPython's MICROPYPATH is ':'-separated everywhere except Windows,
    # where it is ';'. Not os.pathsep on its own: `"win" in sys.platform` is
    # true of "darwin" too, which is the kind of thing that works by luck
    # until the separator differs.
    env["MICROPYPATH"] = (";" if sys.platform.startswith("win")
                          else ":").join(path)
    env["PYTHONPATH"] = os.pathsep.join(path)
    command = [interpreter]
    if "micropython" in Path(interpreter).name:
        command += ["-X", "heapsize=256M"]
    command += [str(PROBES / arguments[0])] + arguments[1:]
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=600, env=env, cwd=str(ROOT))


def _ring_note(output):
    """Say so when the desktop ring dropped blocks under the comparison.

    This used to be the common flake: nothing paced the pump on a desktop, so
    the driver parked it between drains, and a runner busy enough to widen
    that window let the C ring drop whole blocks. The two renders then
    differed for a reason that was not a regression in anything being tested.

    The output ring blocks the pump now, so on a build that has back-pressure
    this note should never fire -- ``ovf`` is 0 by construction and a non-zero
    one means the ring is genuinely too small for a block of the graph
    (live-audio-path-backpressure.md). It stays because the same probes run on
    older interpreters, where the old reading is still the right one.
    """
    dropped = 0
    for line in output.splitlines():
        if " ovf " in line:
            try:
                dropped = max(dropped,
                              int(line.split(" ovf ")[1].split()[0]))
            except (IndexError, ValueError):
                pass
    if not dropped:
        return ""
    return ("\n\nNOTE: the desktop output ring dropped %d block(s) during "
            "this run.\nA busy machine does that on its own -- see "
            "_ring_note() in this file --\nso re-run it on an idle one "
            "before reading this as a regression." % dropped)


class ThePumpProbesRunOnARealInterpreter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.interpreter, cls.why_not = _interpreter()

    def setUp(self):
        if self.interpreter is None:
            if _MISSED.count(self.why_not) == 0:
                _MISSED.append(self.why_not)
            if os.getenv("PYDEVICES_REQUIRE_PUMP") == "1":
                self.fail("PYDEVICES_REQUIRE_PUMP=1 and " + self.why_not)
            self.skipTest("no interpreter with the pump: " + self.why_not)

    def test_the_probes_are_where_the_runner_looks(self):
        """Independent of any interpreter: a probe that was moved or renamed
        must not turn into a silent skip."""
        for _name, arguments, _faults in RUNS:
            self.assertTrue((PROBES / arguments[0]).is_file(),
                            "missing probe " + arguments[0])

    def test_the_contract_and_the_identity_hold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, arguments, _faults in RUNS:
                with self.subTest(probe=name):
                    result = _run(self.interpreter, arguments, tmpdir)
                    self.assertEqual(
                        result.returncode, 0,
                        "%s failed:\n%s\n%s%s"
                        % (name, result.stdout, result.stderr,
                           _ring_note(result.stdout)))

    def test_every_probe_is_shown_failing_on_its_planted_faults(self):
        threaded = bool(_THREADED and _THREADED[0])
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, arguments, faults in RUNS:
                for fault in faults:
                    if fault in THREADED_ONLY and not threaded:
                        why = ("the %s plant on %s needs the pump on its own "
                               "thread; this build has no platform driver"
                               % (fault, name))
                        if why not in _MISSED:
                            _MISSED.append(why)
                        continue
                    with self.subTest(probe=name, fault=fault):
                        result = _run(self.interpreter,
                                      arguments + ["--fault", fault], tmpdir)
                        self.assertNotEqual(
                            result.returncode, 0,
                            "%s passed with the %s fault planted, so it "
                            "proves nothing:\n%s"
                            % (name, fault, result.stdout))


def tearDownModule():
    """Say what was not run, where somebody will see it."""
    if not _MISSED:
        return
    if _THREADED:
        cases = sum(len([f for f in faults if f in THREADED_ONLY])
                    for _name, _args, faults in RUNS)
        headline = ("%d planted fault(s) could not be run on this build"
                    % cases)
    else:
        cases = sum(1 + len(faults) for _name, _args, faults in RUNS)
        headline = ("%d pump probe cases in tests/pump_probes/ were skipped"
                    % cases)
    print("\n" + "!" * 72, file=sys.stderr)
    print("NOT RUN: %s." % headline, file=sys.stderr)
    for why in _MISSED:
        print("         " + why, file=sys.stderr)
    if not _THREADED:
        print("         The pump's C half is UNTESTED in this run. Build an "
              "interpreter with", file=sys.stderr)
        print("         the audioif usermod, point "
              "PYDEVICES_PUMP_INTERPRETER at it, and set", file=sys.stderr)
        print("         PYDEVICES_REQUIRE_PUMP=1 so this can never pass by "
              "skipping.", file=sys.stderr)
    print("!" * 72, file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
