#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""PyDevices Android CLI Runner (android.py)

Drop-in Android interpreter wrapper matching the MicroPython / CPython CLI
interface (-c / -m / <filename> / -i / -X ...).

Stages host Python scripts onto an attached Android device/emulator over adb
and connects terminal stdio/REPL directly to the running on-device app.

Usage:
  android.py script.py [args...]
  android.py -c "import lvgl; print('ok')"
  android.py -m my_module
  android.py -i
  android.py script.py -i
  android.py --install-apk
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import pathlib
import re
import select
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

try:
    import termios
    import tty
except ImportError:  # Native Windows host
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

VERSION = "0.1.0"
PACKAGE_ID_DEFAULT = "org.pydevices.runner"
PACKAGE_ID_LEGACY = "org.pydevices.launcher"
ACTIVITY_DEFAULT = "org.kivy.android.PythonActivity"
STDIO_PORT_DEFAULT = 18765
RUNNER_REPO = "PyDevices/android-runner"
DEFAULT_APK_CACHE_DIR = pathlib.Path.home() / ".pydevices" / "apk"
DEFAULT_APK_FILENAME = "pydevices-runner-debug.apk"


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def find_adb(explicit_adb: Optional[str] = None) -> Optional[str]:
    if explicit_adb:
        return explicit_adb
    env_adb = os.environ.get("ADB")
    if env_adb:
        return env_adb

    # On WSL, check if adb.exe is available in Windows PATH
    if is_wsl():
        which_adb_exe = shutil_which("adb.exe")
        if which_adb_exe:
            return which_adb_exe

    # Check standard SDK candidate paths
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    candidates = []
    if android_home:
        candidates.append(pathlib.Path(android_home) / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb"))
    home = pathlib.Path.home()
    candidates.extend([
        home / "Android" / "Sdk" / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb"),
        home / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        home / ".buildozer" / "android" / "platform" / "android-sdk" / "platform-tools" / "adb",
    ])
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    which_adb = shutil_which("adb")
    if which_adb:
        return which_adb
    if sys.platform == "win32":
        return shutil_which("adb.exe")
    return None


def shutil_which(cmd: str) -> Optional[str]:
    path_env = os.environ.get("PATH", "")
    for p in path_env.split(os.pathsep):
        candidate = pathlib.Path(p) / cmd
        if candidate.is_file() and (sys.platform == "win32" or os.access(candidate, os.X_OK)):
            return str(candidate)
    return None


class AdbClient:
    def __init__(self, adb_bin: str, serial: Optional[str] = None, verbose: int = 0):
        self.adb_bin = adb_bin
        self.serial = serial or os.environ.get("ANDROID_SERIAL")
        self.verbose = verbose

    def _build_cmd(self, args: List[str]) -> List[str]:
        cmd = [self.adb_bin]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return cmd

    def run(self, args: List[str], check: bool = True, capture_output: bool = True, text: bool = True) -> subprocess.CompletedProcess:
        cmd = self._build_cmd(args)
        if self.verbose > 1:
            print(f"android.py: adb command: {' '.join(cmd)}", file=sys.stderr)
        return subprocess.run(cmd, check=check, capture_output=capture_output, text=text)

    def list_devices(self) -> List[str]:
        res = self.run(["devices"], check=False)
        lines = res.stdout.strip().splitlines()
        devices = []
        for line in lines[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def ensure_device(self) -> str:
        devices = self.list_devices()
        if not devices:
            print("android.py: error: no adb device or emulator connected.", file=sys.stderr)
            print("  Please attach an Android device with USB debugging enabled or start an emulator.", file=sys.stderr)
            sys.exit(1)
        if self.serial:
            if self.serial not in devices:
                print(f"android.py: error: specified device '{self.serial}' not found in active devices: {devices}", file=sys.stderr)
                sys.exit(1)
            return self.serial
        if len(devices) > 1:
            self.serial = devices[0]
            print(f"android.py: multiple devices connected; using {self.serial}", file=sys.stderr)
        else:
            self.serial = devices[0]
        return self.serial

    def detect_package_id(self, preferred: str = PACKAGE_ID_DEFAULT) -> Optional[str]:
        # Check preferred package first, then fallback
        for pkg in [preferred, PACKAGE_ID_LEGACY]:
            res = self.run(["shell", "pm", "path", pkg], check=False)
            if res.returncode == 0 and "package:" in res.stdout:
                return pkg
        return None

    def get_installed_version_info(self, package_id: str) -> Tuple[Optional[str], Optional[int]]:
        res = self.run(["shell", "dumpsys", "package", package_id], check=False)
        if res.returncode != 0:
            return None, None
        version_name = None
        version_code = None
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("versionName="):
                version_name = line.split("=", 1)[1]
            elif line.startswith("versionCode="):
                match = re.search(r"versionCode=(\d+)", line)
                if match:
                    version_code = int(match.group(1))
        return version_name, version_code

    def run_as(self, package_id: str, sh_command: str) -> subprocess.CompletedProcess:
        # Quote command for run-as execution inside app data sandbox
        escaped = sh_command.replace("'", "'\"'\"'")
        return self.run(["shell", f"run-as {package_id} sh -c '{escaped}'"], check=False)

    def stage_file(self, package_id: str, host_path: str, dest_rel: str):
        base = os.path.basename(host_path)
        tmp = f"/data/local/tmp/pydevices-runner-{base}"
        self.run(["push", host_path, tmp], check=True)
        dest_dir = os.path.dirname(dest_rel)
        mkdir_cmd = f"mkdir -p files/app/{dest_dir}" if dest_dir else "mkdir -p files/app"
        cp_cmd = f"cp {tmp} files/app/{dest_rel}"
        rm_cmd = f"rm -f {tmp}"
        self.run_as(package_id, f"{mkdir_cmd} && {cp_cmd}")
        self.run(["shell", rm_cmd], check=False)

    def write_app_file(self, package_id: str, dest_rel: str, content: str):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_name = f.name
        try:
            self.stage_file(package_id, tmp_name, dest_rel)
        finally:
            try:
                os.remove(tmp_name)
            except OSError:
                pass

    def install_apk(self, apk_path: pathlib.Path) -> bool:
        print(f"android.py: installing APK: {apk_path} ...", file=sys.stderr)
        res = self.run(["install", "-r", str(apk_path)], check=False)
        if res.returncode == 0 and "Success" in res.stdout:
            print("android.py: APK installation succeeded.", file=sys.stderr)
            return True
        print(f"android.py: error: APK installation failed:\n{res.stdout}\n{res.stderr}", file=sys.stderr)
        return False

    def forward_port(self, local_port: int, remote_port: int):
        self.run(["forward", f"tcp:{local_port}", f"tcp:{remote_port}"], check=True)

    def remove_forward(self, local_port: int):
        self.run(["forward", "--remove", f"tcp:{local_port}"], check=False)

    def force_stop(self, package_id: str):
        self.run(["shell", "am", "force-stop", package_id], check=False)

    def start_activity(self, package_id: str, activity: str):
        self.run(["shell", "am", "start", "-n", f"{package_id}/{activity}"], check=True)


class ReleaseManager:
    def __init__(self, repo: str = RUNNER_REPO, cache_dir: pathlib.Path = DEFAULT_APK_CACHE_DIR):
        self.repo = repo
        self.cache_dir = cache_dir

    def get_latest_release_info(self) -> Optional[dict]:
        url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "PyDevices-Android-Runner"})
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except Exception:
            return None

    def download_release_apk(self, download_url: str, dest_path: pathlib.Path) -> bool:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        print(f"android.py: downloading Runner APK from {download_url} ...", file=sys.stderr)
        req = urllib.request.Request(download_url, headers={"User-Agent": "PyDevices-Android-Runner"})
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp, open(dest_path, "wb") as out_f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_f.write(chunk)
            print(f"android.py: saved APK to {dest_path}", file=sys.stderr)
            return True
        except Exception as exc:
            print(f"android.py: error downloading APK: {exc}", file=sys.stderr)
            return False


def ensure_runner_apk(adb: AdbClient, auto_yes: bool = False, force_update: bool = False, custom_apk_path: Optional[str] = None) -> str:
    if custom_apk_path:
        apk_p = pathlib.Path(custom_apk_path)
        if not apk_p.is_file():
            print(f"android.py: error: custom APK not found: {custom_apk_path}", file=sys.stderr)
            sys.exit(1)
        if not adb.install_apk(apk_p):
            sys.exit(1)
        detected = adb.detect_package_id(PACKAGE_ID_DEFAULT) or PACKAGE_ID_DEFAULT
        return detected

    package_id = adb.detect_package_id(PACKAGE_ID_DEFAULT)
    installed_ver_name, _ = adb.get_installed_version_info(package_id) if package_id else (None, None)

    rel_mgr = ReleaseManager()
    latest_rel = None if (package_id and not force_update) else rel_mgr.get_latest_release_info()
    latest_tag = latest_rel.get("tag_name", "").lstrip("v") if latest_rel else None

    needs_install = False
    action_prompt = ""

    if not package_id:
        needs_install = True
        action_prompt = f"PyDevices Runner APK is not installed on device '{adb.serial}'."
    elif force_update or (latest_tag and installed_ver_name and latest_tag > installed_ver_name):
        needs_install = True
        action_prompt = f"A newer Runner APK is available (installed: {installed_ver_name}, latest: {latest_tag})."

    if needs_install:
        cached_apk = rel_mgr.cache_dir / DEFAULT_APK_FILENAME
        should_proceed = auto_yes
        if not auto_yes:
            if sys.stdin.isatty():
                ans = input(f"android.py: {action_prompt}\nDownload and install Runner APK now? [y/N]: ").strip().lower()
                should_proceed = ans in ("y", "yes")
            else:
                should_proceed = True

        if not should_proceed:
            if not package_id:
                print("android.py: error: cannot continue without installed Runner APK.", file=sys.stderr)
                sys.exit(1)
            print("android.py: continuing with existing installed APK.", file=sys.stderr)
            return package_id

        # Download if needed
        apk_asset_url = None
        if latest_rel and "assets" in latest_rel:
            for asset in latest_rel["assets"]:
                if asset.get("name", "").endswith(".apk"):
                    apk_asset_url = asset.get("browser_download_url")
                    break

        if apk_asset_url:
            if not rel_mgr.download_release_apk(apk_asset_url, cached_apk):
                if not cached_apk.is_file():
                    sys.exit(1)
        elif not cached_apk.is_file():
            print("android.py: warning: unable to check online release and no local cached APK found.", file=sys.stderr)
            if not package_id:
                print("android.py: error: no Runner APK available. Pass --apk-path to specify an APK file.", file=sys.stderr)
                sys.exit(1)
            return package_id

        if not adb.install_apk(cached_apk):
            if not package_id:
                sys.exit(1)

        package_id = adb.detect_package_id(PACKAGE_ID_DEFAULT) or PACKAGE_ID_DEFAULT

    return package_id or PACKAGE_ID_DEFAULT


def drain_stdin(stdin_fd: Optional[int]) -> bool:
    """Non-blocking drain; return True if Ctrl-\\ seen (abort)."""
    if stdin_fd is None or termios is None:
        return False
    abort = False
    try:
        fl = fcntl.fcntl(stdin_fd, fcntl.F_GETFL)
        fcntl.fcntl(stdin_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        try:
            while True:
                try:
                    chunk = os.read(stdin_fd, 256)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                if b"\x1c" in chunk:
                    abort = True
        finally:
            fcntl.fcntl(stdin_fd, fcntl.F_SETFL, fl)
    except Exception:
        pass
    return abort


def try_connect_sidecar(host: str, port: int, mode: str, timeout: float = 1.0) -> Optional[socket.socket]:
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    sock.sendall(f"MODE={mode}\n".encode("utf-8"))
    sock.settimeout(0.35)
    try:
        probe = sock.recv(8, socket.MSG_PEEK)
    except socket.timeout:
        sock.settimeout(None)
        sock.setblocking(False)
        return sock
    except OSError:
        try:
            sock.close()
        except OSError:
            pass
        return None
    if not probe or probe.startswith(b"BUSY"):
        try:
            sock.close()
        except OSError:
            pass
        return None
    sock.settimeout(None)
    sock.setblocking(False)
    return sock


def connect_sidecar_loop(host: str, port: int, mode: str, retries: int = 80, stdin_fd: Optional[int] = None, raw_tty: bool = False) -> Optional[socket.socket]:
    last_err = None

    def _hold_sigint(_signum, _frame):
        pass

    old_handler = signal.signal(signal.SIGINT, _hold_sigint)
    try:
        for attempt in range(max(1, retries)):
            if raw_tty and drain_stdin(stdin_fd):
                print("\r\nandroid.py: aborted (Ctrl-\\)", file=sys.stderr)
                return None
            try:
                sock = try_connect_sidecar(host, port, mode)
                if sock is not None:
                    return sock
                last_err = OSError("adb forward accepted but sidecar not ready")
            except OSError as exc:
                last_err = exc

            for _ in range(5):
                if raw_tty and drain_stdin(stdin_fd):
                    print("\r\nandroid.py: aborted (Ctrl-\\)", file=sys.stderr)
                    return None
                time.sleep(0.05)

            if attempt == 8:
                sys.stderr.write(f"android.py: waiting for app stdio on {host}:{port} (Ctrl-\\ to abort)\r\n")
                sys.stderr.flush()
    finally:
        try:
            signal.signal(signal.SIGINT, old_handler)
        except Exception:
            pass

    print(f"android.py: error: could not connect to {host}:{port} ({last_err})", file=sys.stderr)
    return None


def relay_stdio(sock: socket.socket, stdin_fd: int, sel: selectors.BaseSelector) -> int:
    def _on_sigint(_signum, _frame):
        try:
            sock.sendall(b"\x03")
        except OSError:
            pass

    old_handler = signal.signal(signal.SIGINT, _on_sigint)
    try:
        while True:
            try:
                events = sel.select(timeout=0.5)
            except InterruptedError:
                continue
            for key, _mask in events:
                if key.fileobj is sock:
                    try:
                        data = sock.recv(4096)
                    except BlockingIOError:
                        continue
                    if not data:
                        return 0
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                elif key.fd == stdin_fd:
                    line = sys.stdin.buffer.readline()
                    if not line:
                        return 0
                    try:
                        sock.sendall(line)
                    except OSError:
                        return 0
    finally:
        try:
            signal.signal(signal.SIGINT, old_handler)
        except Exception:
            pass


def relay_repl_raw(sock: socket.socket, stdin_fd: int, sel: selectors.BaseSelector, saved_termios=None) -> int:
    assert termios is not None and tty is not None
    try:
        while True:
            try:
                events = sel.select(timeout=0.5)
            except InterruptedError:
                continue
            for key, _mask in events:
                if key.fileobj is sock:
                    try:
                        data = sock.recv(4096)
                    except BlockingIOError:
                        continue
                    if not data:
                        return 0
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                elif key.fd == stdin_fd:
                    try:
                        chunk = os.read(stdin_fd, 256)
                    except OSError:
                        return 0
                    if not chunk:
                        return 0
                    # Ctrl-\ : leave attach (app continues)
                    if b"\x1c" in chunk:
                        return 0
                    try:
                        sock.sendall(chunk)
                    except OSError:
                        return 0
    finally:
        if saved_termios is not None:
            try:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved_termios)
            except Exception:
                pass
            try:
                sys.stdout.write("\r\n")
                sys.stdout.flush()
            except Exception:
                pass


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android.py",
        description="PyDevices Android CLI interpreter runner (MicroPython CLI parity).",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="show this help message and exit")
    parser.add_argument("--version", action="store_true", help="show version information and exit")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output (can be specified multiple times)")
    parser.add_argument("-s", "--device", dest="serial", help="adb device serial number")
    parser.add_argument("-i", "--repl", action="store_true", help="enable inspection via REPL after running command/module/file")
    parser.add_argument("-c", dest="command", help="program passed in as string")
    parser.add_argument("-m", dest="module", help="run library module as a script")
    parser.add_argument("-O", dest="optimize", nargs="?", const="1", help="accepted for MicroPython/CPython parity (no-op)")
    parser.add_argument("-X", dest="x_opt", action="append", default=[], help="implementation specific options (accepted for MicroPython parity)")

    # Android specific flags
    parser.add_argument("--clear", action="store_true", help="restore default launcher; clear run/ directory")
    parser.add_argument("--no-attach", action="store_true", help="launch only; do not wire this terminal to app stdio")
    parser.add_argument("--logcat", action="store_true", help="stream logcat output after launch")
    parser.add_argument("--hold-s", type=float, help="keep presenting for SEC seconds after oneshot script returns")
    parser.add_argument("--install-apk", action="store_true", help="download and install/reinstall latest Runner APK")
    parser.add_argument("--update-apk", action="store_true", help="check for and install APK updates")
    parser.add_argument("--apk-path", help="path to custom APK file to install")
    parser.add_argument("-y", "--yes", action="store_true", help="automatic yes to prompts (for CI/automation)")
    parser.add_argument("--port", type=int, default=STDIO_PORT_DEFAULT, help=f"stdio sidecar port (default: {STDIO_PORT_DEFAULT})")
    parser.add_argument("--kit", action="store_true", help="run the entry in example_test_kit mode (run_argv=kit; stages quit_inject.py)")
    parser.add_argument("--modules", help="comma-separated pydevices-examples lib/examples modules to stage beside the entry")
    parser.add_argument("--manifests", help="comma-separated pydevices-examples packages/*.json manifests to stage")
    parser.add_argument("--deps", help="comma-separated dependency names (informational; the APK bakes the core stack)")

    # Positional script and its arguments
    parser.add_argument("script", nargs="?", help="Python script file to execute")
    parser.add_argument("script_args", nargs=argparse.REMAINDER, help="arguments passed to the script")
    return parser


def _examples_roots() -> List[pathlib.Path]:
    """Candidate pydevices-examples checkouts, most explicit first."""
    env = os.environ.get("PYDEVICES_EXAMPLES_ROOT")
    roots = [pathlib.Path(env)] if env else []
    here = pathlib.Path(__file__).resolve()
    roots.append(here.parent.parent.parent / "pydevices-examples")
    return roots


def _find_in_examples(*parts: str) -> Optional[pathlib.Path]:
    """First existing pydevices-examples file at the given relative path."""
    for root in _examples_roots():
        candidate = root.joinpath(*parts)
        if candidate.is_file():
            return candidate
    return None


def _find_quit_inject() -> Optional[pathlib.Path]:
    """Locate pydevices-examples/tools/quit_inject.py in a sibling checkout."""
    return _find_in_examples("tools", "quit_inject.py")


def _csv(value: Optional[str]) -> List[str]:
    """Split a comma-separated flag value, ignoring blanks and whitespace."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _stage_companions(adb, package_id: str, args) -> None:
    """Stage the extra example modules and MIP manifests named on the CLI.

    Mirrors --modules / --manifests / --deps from the older android.sh, with the
    example path corrected: sources moved from src/examples/ to lib/examples/.
    """
    for name in _csv(getattr(args, "modules", None)):
        found = _find_in_examples("lib", "examples", name + ".py")
        if found is not None:
            adb.stage_file(package_id, str(found), "run/{}.py".format(name))
            print("android.py: staged module {}".format(name), file=sys.stderr)
        else:
            print("android.py: warning: module not found: {}".format(name), file=sys.stderr)

    for name in _csv(getattr(args, "manifests", None)):
        found = _find_in_examples("packages", name + ".json")
        if found is not None:
            adb.stage_file(package_id, str(found), "run/{}.json".format(name))
            print("android.py: staged manifest {}".format(name), file=sys.stderr)
        else:
            print("android.py: warning: manifest not found: {}".format(name), file=sys.stderr)

    for name in _csv(getattr(args, "deps", None)):
        # Documentation only: the core stack is baked into the Runner APK.
        print(
            "android.py: note: --deps {} (the APK should already provide it)".format(name),
            file=sys.stderr,
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.help:
        parser.print_help()
        print("\nMicroPython compatibility notes:")
        print("  -c <cmd> | -m <mod> | <filename> are mutually exclusive.")
        print("  -O and -X options are accepted for CLI parity.")
        print("  Ctrl-C sends SIGINT (\\x03) to on-device interpreter.")
        print("  Ctrl-\\ detaches the host terminal without killing the on-device app.")
        return 0

    if args.version:
        print(f"PyDevices android.py version {VERSION}")
        adb_path = find_adb()
        if adb_path:
            adb = AdbClient(adb_path, serial=args.serial, verbose=args.verbose)
            devices = adb.list_devices()
            print(f"ADB: {adb_path} (connected devices: {len(devices)})")
            if devices:
                pkg = adb.detect_package_id()
                if pkg:
                    ver_name, ver_code = adb.get_installed_version_info(pkg)
                    print(f"Device [{devices[0]}] installed APK: {pkg} (versionName={ver_name}, versionCode={ver_code})")
        return 0

    # Validate mutually exclusive entrypoints
    n_entry = sum(1 for x in (args.command, args.module, args.script) if x)
    if n_entry > 1:
        print("android.py: error: use only one of -c, -m, or <filename>", file=sys.stderr)
        return 1

    adb_path = find_adb()
    if not adb_path:
        print("android.py: error: adb executable not found.", file=sys.stderr)
        print("  Please install Android platform-tools or set ANDROID_HOME / PATH.", file=sys.stderr)
        return 1

    adb = AdbClient(adb_path, serial=args.serial, verbose=args.verbose)
    adb.ensure_device()

    package_id = ensure_runner_apk(
        adb,
        auto_yes=args.yes,
        force_update=args.update_apk or args.install_apk,
        custom_apk_path=args.apk_path,
    )

    if args.clear:
        print(f"android.py: clearing staged run/ and restoring default entry on {package_id}...", file=sys.stderr)
        adb.run_as(package_id, "rm -rf files/app/run files/app/run_entry files/app/run_argv")
        adb.force_stop(package_id)
        adb.start_activity(package_id, ACTIVITY_DEFAULT)
        return 0

    entry_name = ""
    # Stage target
    if args.command is not None:
        cmd_content = (
            "import sys\n"
            "sys.argv[0] = '-c'\n"
            f"exec(compile({args.command!r}, '<string>', 'exec'))\n"
        )
        adb.run_as(package_id, "rm -rf files/app/run; mkdir -p files/app/run")
        adb.write_app_file(package_id, "run/_android_c.py", cmd_content)
        entry_name = "_android_c"
        if args.verbose:
            print(f"android.py: staged command into run/_android_c.py", file=sys.stderr)

    elif args.script:
        script_path = pathlib.Path(args.script).resolve()
        if not script_path.is_file():
            print(f"android.py: error: script file not found: {args.script}", file=sys.stderr)
            return 1

        stem = script_path.stem
        entry_name = stem
        adb.run_as(package_id, "rm -rf files/app/run; mkdir -p files/app/run")
        adb.stage_file(package_id, str(script_path), f"run/{stem}.py")
        if args.verbose:
            print(f"android.py: staged {script_path} -> run/{stem}.py", file=sys.stderr)

        # Stage sibling files / assets if part of a directory
        parent_dir = script_path.parent
        for sibling in parent_dir.iterdir():
            if sibling.is_file() and sibling != script_path and sibling.suffix in (".py", ".json", ".txt"):
                adb.stage_file(package_id, str(sibling), f"run/{sibling.name}")
        assets_dir = parent_dir / "assets"
        if assets_dir.is_dir():
            adb.run_as(package_id, "mkdir -p files/app/run/assets")
            for asset in assets_dir.iterdir():
                if asset.is_file():
                    adb.stage_file(package_id, str(asset), f"run/assets/{asset.name}")

        _stage_companions(adb, package_id, args)

        # example_test_kit mode: the entry reads run_argv == "kit" and switches to
        # a timed, self-quitting run. lv_test_timer's kit path imports quit_inject,
        # so stage it beside the entry from a sibling pydevices-examples checkout.
        if args.kit:
            adb.write_app_file(package_id, "run_argv", "kit")
            quit_inject = _find_quit_inject()
            if quit_inject is not None:
                adb.stage_file(package_id, str(quit_inject), "run/quit_inject.py")
                print(f"android.py: staged quit_inject.py for kit mode", file=sys.stderr)
            else:
                print("android.py: warning: kit mode but tools/quit_inject.py not found", file=sys.stderr)

        # Write run_argv if script arguments were provided
        elif args.script_args:
            argv_str = " ".join([script_path.name] + args.script_args)
            adb.write_app_file(package_id, "run_argv", argv_str)
        else:
            adb.run_as(package_id, "rm -f files/app/run_argv")

    elif args.module:
        entry_name = args.module.replace("examples.", "")

    if entry_name:
        if args.hold_s:
            hold_code = (
                f"import importlib, time\n"
                f"importlib.import_module({entry_name!r})\n"
                f"try:\n"
                f"    from board_config import display_drv\n"
                f"except Exception:\n"
                f"    display_drv = None\n"
                f"_deadline = time.time() + {float(args.hold_s)!r}\n"
                f"while time.time() < _deadline:\n"
                f"    if display_drv is not None:\n"
                f"        try:\n"
                f"            display_drv.show()\n"
                f"        except Exception:\n"
                f"            pass\n"
                f"    time.sleep(0.05)\n"
            )
            adb.write_app_file(package_id, "run/_android_hold.py", hold_code)
            adb.write_app_file(package_id, "main.py", "import _android_hold")
        else:
            adb.write_app_file(package_id, "main.py", f"import {entry_name}")
    elif args.repl:
        # Bare -i: omit main.py for clean REPL
        adb.run_as(package_id, "rm -rf files/app/run files/app/run_entry files/app/run_argv files/app/main.py files/app/main.pyc")

    # Launch Activity
    adb.force_stop(package_id)
    adb.start_activity(package_id, ACTIVITY_DEFAULT)
    if args.verbose:
        print(f"android.py: launched {package_id}/{ACTIVITY_DEFAULT}", file=sys.stderr)

    if args.no_attach:
        return 0

    if args.logcat and not args.repl:
        adb.run(["logcat", "-c"], check=False)
        cmd = [adb_path]
        if adb.serial:
            cmd.extend(["-s", adb.serial])
        cmd.extend(["logcat", "-v", "time", "python:V", "SDL:V", "AndroidRuntime:E", "*:S"])
        return subprocess.run(cmd).returncode

    # Stdio attach
    adb.forward_port(args.port, args.port)
    mode = "repl" if args.repl else "stdio"

    stdin_fd = None
    try:
        stdin_fd = sys.stdin.fileno()
    except Exception:
        stdin_fd = None

    use_raw = (
        mode == "repl"
        and stdin_fd is not None
        and sys.stdin.isatty()
        and termios is not None
        and tty is not None
    )

    saved_termios = None
    if use_raw and termios is not None and tty is not None:
        saved_termios = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)

    try:
        sock = connect_sidecar_loop("127.0.0.1", args.port, mode, retries=80, stdin_fd=stdin_fd, raw_tty=use_raw)
        if sock is None:
            return 1

        sel = selectors.DefaultSelector()
        try:
            if stdin_fd is not None:
                sel.register(stdin_fd, selectors.EVENT_READ)
            sel.register(sock, selectors.EVENT_READ)

            if use_raw:
                saved = saved_termios
                saved_termios = None
                return relay_repl_raw(sock, stdin_fd, sel, saved_termios=saved)
            if stdin_fd is None:
                return 1
            try:
                sys.stdin.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
            except Exception:
                pass
            return relay_stdio(sock, stdin_fd, sel)
        finally:
            try:
                sel.close()
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
    finally:
        adb.remove_forward(args.port)
        if use_raw and saved_termios is not None and termios is not None:
            try:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved_termios)
            except Exception:
                pass
            try:
                sys.stdout.write("\r\n")
                sys.stdout.flush()
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        try:
            sys.stdout.write("\r\n")
            sys.stdout.flush()
        except Exception:
            pass
        sys.exit(130)
