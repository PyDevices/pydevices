// The direct MicroPython WebAssembly runtime, as Workbench and the PyDevices
// gallery load it: loadMicroPython() from micropython.mjs, files written into
// its filesystem, Python run with runPythonAsync(). serve.py maps /wasm/ to
// the workspace's bin/ directory.
const FILES = ["__init__", "auto", "nus", "webble"].map((m) => [`../../lib/bledev/${m}.py`, `/lib/bledev/${m}.py`]);
FILES.push(["./gate.py", "/lib/gate.py"]);

const { loadMicroPython } = await import("/wasm/micropython.mjs");
const mp = await loadMicroPython({ stdout: (line) => console.log(line), linebuffer: true, heapsize: 16 * 1024 * 1024 });
mp.FS.mkdirTree("/lib/bledev");
for (const [url, path] of FILES) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  mp.FS.writeFile(path, await response.text());
}
try {
  await mp.runPythonAsync("import sys\nif '/lib' not in sys.path: sys.path.append('/lib')\nimport gate");
} catch (e) {
  window.gateLog("PYTHON ERROR " + e);
}
