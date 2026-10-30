# SPDX-License-Identifier: MIT
"""The pins behind a final release's interpreters: scripts/release_interpreters/sources.py,
the gate and fetch steps of scripts/release_interpreters.sh, and the sources
record bin/upload_interpreters.sh puts in interpreters.json.

Everything runs against throwaway git repositories on disk; nothing is fetched
from GitHub.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SOURCES_PY = SCRIPTS / "release_interpreters" / "sources.py"

spec = importlib.util.spec_from_file_location("release_interpreters_sources", str(SOURCES_PY))
assert spec and spec.loader
sources = importlib.util.module_from_spec(spec)
sys.modules["release_interpreters_sources"] = sources
spec.loader.exec_module(sources)

HAVE_BASH = shutil.which("bash") is not None and shutil.which("git") is not None


def git(directory, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    return subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def make_repo(path, files, message="commit"):
    """A git repository at path with files written and committed; returns its HEAD."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        git(path, "init", "-q", "-b", "main")
    for name, text in files.items():
        (path / name).write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def lock(self, mpp, lvgl, comment="# pins\n"):
        path = self.dir / "sources.lock"
        path.write_text(f"{comment}micropython-pydevices   {self.dir}/mpp   {mpp}\n"
                        f"omnipython-lvgl         {self.dir}/lvgl  {lvgl}  # trailing note\n")
        return path


class TheShippedLock(unittest.TestCase):
    def test_pins_both_sources_at_full_commits(self):
        pins = sources.pins()
        self.assertEqual(set(pins), {"micropython-pydevices", "omnipython-lvgl"})
        for name, (url, commit) in pins.items():
            self.assertRegex(commit, r"^[0-9a-f]{40}$", name)
            self.assertTrue(url.startswith("https://github.com/PyDevices/"), name)


class ReadingPins(Scratch):
    def test_pins_prints_the_workflow_outputs(self):
        lock = self.lock("a" * 40, "b" * 40)
        out = subprocess.run([sys.executable, str(SOURCES_PY), "--lock", str(lock), "pins"],
                             check=True, capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["mpp=" + "a" * 40, "lvgl=" + "b" * 40])

    def test_a_short_commit_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            sources.pins(self.lock("abc1234", "b" * 40))
        self.assertIn("40-character", str(cm.exception))

    def test_a_branch_name_is_refused(self):
        with self.assertRaises(SystemExit):
            sources.pins(self.lock("main", "b" * 40))

    def test_a_missing_source_is_refused(self):
        path = self.dir / "sources.lock"
        path.write_text(f"micropython-pydevices https://example.com/x.git {'a' * 40}\n")
        with self.assertRaises(SystemExit) as cm:
            sources.pins(path)
        self.assertIn("omnipython-lvgl", str(cm.exception))

    def test_a_row_of_the_wrong_shape_is_refused(self):
        path = self.dir / "sources.lock"
        path.write_text("micropython-pydevices https://example.com/x.git\n")
        with self.assertRaises(SystemExit):
            sources.pins(path)


@unittest.skipUnless(HAVE_BASH, "needs git")
class Bumping(Scratch):
    def setUp(self):
        super().setUp()
        self.mpp_old = make_repo(self.dir / "mpp", {"a": "1"})
        self.lvgl_old = make_repo(self.dir / "lvgl", {"a": "1"})
        self.path = self.lock(self.mpp_old, self.lvgl_old)
        self.mpp_new = make_repo(self.dir / "mpp", {"a": "2"})

    def test_moves_a_pin_to_the_tip_and_keeps_the_comments(self):
        sources.bump(self.path)
        pins = sources.pins(self.path)
        self.assertEqual(pins["micropython-pydevices"][1], self.mpp_new)
        self.assertEqual(pins["omnipython-lvgl"][1], self.lvgl_old)
        text = self.path.read_text()
        self.assertTrue(text.startswith("# pins\n"))
        self.assertIn("# trailing note", text)

    def test_dry_run_changes_nothing(self):
        before = self.path.read_text()
        sources.bump(self.path, dry_run=True)
        self.assertEqual(self.path.read_text(), before)

    def test_stale_names_the_pin_that_is_behind(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sources.stale(self.path)
        self.assertIn("micropython-pydevices pin is behind", buf.getvalue())
        self.assertNotIn("omnipython-lvgl pin", buf.getvalue())


@unittest.skipUnless(HAVE_BASH, "needs git")
class TheSourcesRecord(Scratch):
    def setUp(self):
        super().setUp()
        self.mpp = make_repo(self.dir / "mpp", {
            "UPSTREAM": "c" * 40 + "\n",
            "modules.lock": f"# modules\npydevices https://example.com/pydevices.git {'1' * 40}\n"
                            f"omnipython-lib https://example.com/pydevices.git {'3' * 40}\n"
                            f"displayif https://example.com/displayif.git {'2' * 40}\n",
            "deps.lock": "esp-idf https://example.com/idf.git v5.5.4\n"
                         "circuitpython https://example.com/cp.git 11.0.0-alpha.1\n",
        })
        self.lvgl = make_repo(self.dir / "lvgl", {"a": "1"})
        self.pyd = make_repo(self.dir / "pyd", {"a": "1"})

    def record(self, lock):
        return sources.record(self.dir / "mpp", self.dir / "lvgl", self.dir / "pyd", "v1.2.3", lock)

    def test_lists_every_commit_the_build_used(self):
        rec = self.record(self.lock(self.mpp, self.lvgl))
        self.assertTrue(rec["pinned"])
        self.assertEqual(rec["pydevices"], {"commit": self.pyd, "ref": "v1.2.3"})
        self.assertEqual(rec["micropython-pydevices"], {"commit": self.mpp})
        self.assertEqual(rec["omnipython-lvgl"], {"commit": self.lvgl})
        self.assertEqual(rec["micropython"], {"commit": "c" * 40})
        self.assertEqual(rec["circuitpython"], {"version": "11.0.0-alpha.1"})

    def test_pydevices_comes_from_the_release_not_modules_lock(self):
        rec = self.record(self.lock(self.mpp, self.lvgl))
        self.assertEqual(rec["modules"], {"displayif": "2" * 40})

    def test_says_unpinned_when_a_checkout_is_not_the_pin(self):
        rec = self.record(self.lock(self.mpp, "d" * 40))
        self.assertFalse(rec["pinned"])
        rec = self.record(self.lock("d" * 40, self.lvgl))
        self.assertFalse(rec["pinned"])

    def test_verify_fails_on_the_wrong_commit(self):
        lock = self.lock("d" * 40, self.lvgl)
        with self.assertRaises(SystemExit):
            sources.verify("micropython-pydevices", self.dir / "mpp", lock)
        sources.verify("omnipython-lvgl", self.dir / "lvgl", lock)


@unittest.skipUnless(HAVE_BASH, "needs bash and git")
class TheWorkflowSteps(Scratch):
    """release_interpreters.sh, run from a copy whose sources.lock points at local repositories."""

    def setUp(self):
        super().setUp()
        self.mpp = make_repo(self.dir / "mpp", {"a": "1"})
        self.lvgl = make_repo(self.dir / "lvgl", {"a": "1"})
        self.tree = self.dir / "scripts"
        shutil.copytree(SCRIPTS / "release_interpreters", self.tree / "release_interpreters",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(SCRIPTS / "release_interpreters.sh", self.tree)
        (self.tree / "release_interpreters" / "sources.lock").write_text(
            f"micropython-pydevices {self.dir}/mpp {self.mpp}\nomnipython-lvgl {self.dir}/lvgl {self.lvgl}\n")

    def sh(self, *args, check=True):
        return subprocess.run(["bash", str(self.tree / "release_interpreters.sh"), *args],
                              capture_output=True, text=True, check=check)

    def test_gate_prints_the_pins_for_the_workflow(self):
        out = dict(line.split("=", 1) for line in self.sh("gate", "release", "v1.2.3").stdout.split())
        self.assertEqual(out["build"], "true")
        self.assertEqual(out["attach"], "true")
        self.assertEqual(out["mpp"], self.mpp)
        self.assertEqual(out["lvgl"], self.lvgl)

    def test_gate_refuses_to_attach_a_build_of_another_source(self):
        for mpp_ref, lvgl_ref in (("main", ""), ("", "feature")):
            r = self.sh("gate", "workflow_dispatch", "v1.2.3", "true", mpp_ref, lvgl_ref, check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("sources.lock", r.stderr)

    def test_gate_lets_a_trial_build_use_another_source(self):
        r = self.sh("gate", "workflow_dispatch", "feature", "false", "main", "main")
        self.assertIn("attach=false", r.stdout)

    def test_gate_stops_on_a_bad_lock(self):
        (self.tree / "release_interpreters" / "sources.lock").write_text("micropython-pydevices x y\n")
        self.assertNotEqual(self.sh("gate", "release", "v1.2.3", check=False).returncode, 0)

    def test_fetch_checks_out_the_pinned_commit_not_the_tip(self):
        make_repo(self.dir / "lvgl", {"a": "2"})
        # The pin is no longer the tip; a fetch by commit needs the server to allow it.
        git(self.dir / "lvgl", "config", "uploadpack.allowAnySHA1InWant", "true")
        self.sh("fetch", "omnipython-lvgl", str(self.dir / "out"))
        self.assertEqual(git(self.dir / "out", "rev-parse", "HEAD"), self.lvgl)
        self.assertEqual((self.dir / "out" / "a").read_text(), "1")

    def test_fetch_stops_when_the_pinned_commit_is_gone(self):
        lock = self.tree / "release_interpreters" / "sources.lock"
        lock.write_text(lock.read_text().replace(self.lvgl, "e" * 40))
        r = self.sh("fetch", "omnipython-lvgl", str(self.dir / "out"), check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_fetch_takes_another_ref_when_asked(self):
        new = make_repo(self.dir / "lvgl", {"a": "2"})
        self.sh("fetch", "omnipython-lvgl", str(self.dir / "out"), "main")
        self.assertEqual(git(self.dir / "out", "rev-parse", "HEAD"), new)


@unittest.skipUnless(HAVE_BASH, "needs bash")
class TheManifest(Scratch):
    def test_carries_the_sources_record(self):
        bindir = self.dir / "bin"
        bindir.mkdir()
        shutil.copy(ROOT / "bin" / "upload_interpreters.sh", bindir)
        for name in ("micropython", "circuitpython"):
            (bindir / name).write_text("#!/bin/sh\necho 3.4.0\n")
            (bindir / name).chmod(0o755)
        for name in ("micropython.exe", "micropython.mjs", "micropython.wasm"):
            (bindir / name).write_text("x")
        record = {"pinned": True, "micropython-pydevices": {"commit": "a" * 40}, "modules": {"m": "b" * 40}}
        (self.dir / "sources.json").write_text(json.dumps(record, indent=2))
        env = dict(os.environ, DRY_RUN="1", SOURCES_JSON=str(self.dir / "sources.json"))
        subprocess.run(["bash", str(bindir / "upload_interpreters.sh"), "v1.2.3"], check=True,
                       capture_output=True, env=env)
        manifest = json.loads((bindir / "interpreters.json").read_text())
        self.assertEqual(manifest["sources"], record)
        self.assertIn("micropython.wasm", manifest["files"])

    def test_without_a_record_the_manifest_is_as_before(self):
        text = (ROOT / "bin" / "upload_interpreters.sh").read_text()
        self.assertIn('if [[ -n "${SOURCES_JSON:-}" ]]', text)


NOTES_PY = SCRIPTS / "release_interpreters" / "notes.py"
spec = importlib.util.spec_from_file_location("release_interpreters_notes", str(NOTES_PY))
assert spec and spec.loader
notes = importlib.util.module_from_spec(spec)
sys.modules["release_interpreters_notes"] = notes
spec.loader.exec_module(notes)

def manifest(mp, cp):
    return {"built_on": {"micropython": mp, "circuitpython": cp}}


class TheReleaseNotesLine(unittest.TestCase):
    def test_says_both_are_previews(self):
        self.assertEqual(notes.line(manifest("1.30.0-preview", "11.0.0-alpha.1")),
                         notes.MARK + "The attached interpreters are built on MicroPython "
                         "1.30.0-preview (a preview) and CircuitPython 11.0.0-alpha.1 (a preview).")

    def test_labels_only_the_one_that_is_a_preview(self):
        text = notes.line(manifest("1.29.0", "11.0.0-alpha.1"))
        self.assertIn("MicroPython 1.29.0 and", text)
        self.assertIn("CircuitPython 11.0.0-alpha.1 (a preview).", text)
        text = notes.line(manifest("1.30.0-preview", "10.1.0"))
        self.assertIn("(a preview) and CircuitPython 10.1.0.", text)

    def test_calls_nothing_a_preview_when_both_are_releases(self):
        text = notes.line(manifest("1.29.0", "10.1.0"))
        self.assertNotIn("preview", text)
        self.assertIn("MicroPython 1.29.0 and CircuitPython 10.1.0.", text)

    def test_a_build_past_a_tag_is_not_a_release(self):
        self.assertIn("1.29.0-12-gabc1234 (a preview)", notes.line(manifest("1.29.0-12-gabc1234", "10.1.0")))

    def test_reads_the_versions_and_does_not_invent_them(self):
        text = notes.line(manifest("9.9.9-preview", "8.8.8-beta.2"))
        self.assertIn("9.9.9-preview (a preview)", text)
        self.assertIn("8.8.8-beta.2 (a preview)", text)

    def test_stops_when_the_manifest_does_not_say(self):
        for bad in ({}, {"built_on": {"micropython": "1.29.0"}}, manifest("", "10.1.0")):
            with self.assertRaises(SystemExit):
                notes.line(bad)


class PuttingTheLineInTheNotes(unittest.TestCase):
    def test_goes_last_after_a_blank_line(self):
        body = "## What's Changed\n* a thing\n\n**Full Changelog**: https://example.com\n"
        self.assertEqual(notes.with_line(body, notes.MARK + "X."), body + "\n" + notes.MARK + "X.\n")

    def test_an_empty_body_is_just_the_line(self):
        self.assertEqual(notes.with_line("", notes.MARK + "X."), notes.MARK + "X.\n")

    def test_a_second_run_replaces_the_line(self):
        once = notes.with_line("Notes.\n", notes.MARK + "old.")
        twice = notes.with_line(once, notes.MARK + "new.")
        self.assertEqual(twice, "Notes.\n\n" + notes.MARK + "new.\n")


@unittest.skipUnless(HAVE_BASH, "needs bash")
class TheLineFromARealManifest(Scratch):
    """upload_interpreters.sh writes the manifest the workflow gives notes.py."""

    def make_bin(self, mp, cp):
        bindir = self.dir / "bin"
        bindir.mkdir()
        shutil.copy(ROOT / "bin" / "upload_interpreters.sh", bindir)
        # sys.version is what the manifest's per-file "version" holds; a build with
        # no git tags says a commit there, so MicroPython's number is asked of
        # sys.implementation instead.
        (bindir / "micropython").write_text(
            "#!/bin/sh\n"
            f'case "$2" in *sys.implementation*) echo "{mp}";; *) echo "3.4.0; MicroPython 02b9097057-dirty on 2026-10-21";; esac\n')
        (bindir / "circuitpython").write_text(f"#!/bin/sh\necho '3.4.0; CircuitPython {cp}-dirty on 2026-10-21'\n")
        for name in ("micropython", "circuitpython"):
            (bindir / name).chmod(0o755)
        for name in ("micropython.exe", "micropython.mjs", "micropython.wasm"):
            (bindir / name).write_text("x")
        subprocess.run(["bash", str(bindir / "upload_interpreters.sh"), "v1.2.3"], check=True,
                       capture_output=True, env=dict(os.environ, DRY_RUN="1"))
        return bindir / "interpreters.json"

    def test_line_command_reads_the_file(self):
        path = self.make_bin("1.30.0-preview", "11.0.0-alpha.1")
        out = subprocess.run([sys.executable, str(NOTES_PY), "line", str(path)], check=True,
                             capture_output=True, text=True).stdout
        self.assertIn("MicroPython 1.30.0-preview (a preview) and CircuitPython 11.0.0-alpha.1 (a preview)", out)
        recorded = json.loads(path.read_text())
        self.assertEqual(recorded["built_on"], {"micropython": "1.30.0-preview", "circuitpython": "11.0.0-alpha.1"})
        self.assertIn("02b9097057-dirty", recorded["files"]["micropython"]["version"])

    def test_release_command_edits_the_notes_through_gh(self):
        path = self.make_bin("1.29.0", "11.0.0-alpha.1")
        fake = self.dir / "fakebin"
        fake.mkdir()
        gh = fake / "gh"
        gh.write_text("#!/bin/bash\n"
                      'if [[ "$2" == view ]]; then printf "Release notes.\\n"; exit 0; fi\n'
                      'while [[ $# -gt 0 ]]; do [[ "$1" == --notes-file ]] && cp "$2" "$GH_OUT"; shift; done\n')
        gh.chmod(0o755)
        env = dict(os.environ, PATH=f"{fake}{os.pathsep}{os.environ['PATH']}", GH_OUT=str(self.dir / "out.md"))
        subprocess.run([sys.executable, str(NOTES_PY), "release", "v1.2.3", str(path)], check=True,
                       capture_output=True, env=env)
        self.assertEqual((self.dir / "out.md").read_text(),
                         "Release notes.\n\n" + notes.MARK + "The attached interpreters are built on MicroPython "
                         "1.29.0 and CircuitPython 11.0.0-alpha.1 (a preview).\n")


if __name__ == "__main__":
    unittest.main()
