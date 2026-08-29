# Timer backend internals & platform capabilities

This document explains the internal architecture of `multimer`: how timer providers are selected, the underlying C-binding and threading capabilities of each Python interpreter, and how PyDevices bridges hardware interrupts, OS signals, and SDL2 event pumps.

Importing `multimer` itself never selects a synchronous timer provider. An
application imports a provider explicitly, such as
`from multimer import librt as timer`, or opts into platform selection with
`from multimer import auto as timer`. The final column below describes what
`multimer.auto` normally selects; it is not a package-root default.

For the general user guide and quickstart, see [multimer](multimer.md). For display driver integration, see [Display backend internals](displaydev-internals.md) and [App and board config](app-and-board-config.md).

---

## Platform capabilities matrix

The table below details the underlying system capabilities available to `multimer` across all supported interpreters:

| Interpreter / Executable | Target Platform | FFI / C-Bindings | Threading Support | SDL2 Provider | Signal / Interrupt Timers | Normal `multimer.auto` Provider |
|---|---|---|---|---|---|---|
| **CPython** (`python`) | Linux Desktop | `ctypes` | Full `threading` + `_thread` | `usdl2.py` (via `ctypes`) or `pygame` | POSIX real-time signals (`librt`) | `librt` (`uses_interrupts=True`) |
| **MicroPython** (`micropython`) | Linux Unix port | `ffi` + `uctypes` | Built-in `_thread` | `usdl2.py` (via `ffi`) | POSIX real-time signals (`librt`) | `librt` (`uses_interrupts=True`) |
| **CircuitPython** (`circuitpython`) | Linux port | None | Built-in `_thread` | `displayif` (compiled C module) | None | `sdl2` / `polling` (`uses_interrupts=False`) |
| **CPython** (`python.exe`) | Windows | `ctypes` | Full `threading` + `_thread` | `usdl2.py` (via `ctypes`) or `pygame-ce` | Waitable Timer APCs (`uwin32.py`) | `win32` (`uses_interrupts=True`) |
| **MicroPython** (`micropython.exe`) | Windows Win32 port | `ffi` + `uctypes` | None | `displayif` (compiled C module) | Waitable Timer APCs (`uwin32.py`) | `win32` (`uses_interrupts=True`) |
| **CPython** (`python`) | Android | `ctypes` | Full `threading` + `_thread` | `pygame` / native Android surface | None | `threading` (`uses_interrupts=False`) |
| **MicroPython** | MCU Boards | None / Native C | Port-dependent `_thread` | N/A (Direct panel bus) | Hardware interrupts (`machine.Timer`) | `machine` (`uses_interrupts=True`) |
| **CircuitPython** | MCU Boards | None | None | N/A (Direct panel bus) | None | `polling` (`uses_interrupts=False`) |

| **PyScript / Pyodide** | Browser / WASM | `js` / `pyodide` FFI | None (single-threaded WASM) | HTML5 Canvas | Browser host loop / Web APIs | internal async provider (`uses_interrupts=False`) |

---

## How SDL2 is bridged (`usdl2.py` vs `displayif`)

Hosted desktop and simulation targets often use SDL2 for window management, frame presentation, and input polling. PyDevices provides two distinct mechanisms to connect to SDL2 depending on the host's FFI capabilities:

### 1. Pure-Python FFI Bridge (`usdl2.py`)
When running on **CPython** (Linux/Windows) or **MicroPython Unix** (Linux), the interpreter has access to dynamic foreign function interfaces (`ctypes` or `ffi`):
* [`usdl2.py`](../utils/usdl2.py) dynamically loads the system `libSDL2.so` or `SDL2.dll` at app.
* No C compilation or custom binary build is needed.
* Timer ticks and window pump hooks can be called directly from Python code.

### 2. Compiled User C Module (`displayif` / `cmods`)
When running on interpreters **without FFI** (such as CircuitPython, or a custom
MicroPython build that omits `ffi`):
* Python cannot load DLLs or shared libraries dynamically.
* The [cmods](https://github.com/PyDevices/cmods) workspace compiles `displayif` directly into the interpreter binary as a native C module (`usdl2`).
* Python code imports `usdl2` as a built-in module, exposing identical SDL function signatures without requiring runtime FFI.

---

## Signal & Interrupt Timer Delivery

Providers with `uses_interrupts is True` deliver callbacks directly to the
main thread through interrupts, signals, or equivalent OS delivery. This
eliminates the need for an application-level timer pump and enables the
**Interactive REPL** debugging workflow. `uses_interrupts` is provider metadata,
not a `Timer` class method, because it describes delivery by the provider as a
whole and also governs `sleep_ms` and `pump` behavior.

### 1. Linux `librt` (POSIX Signals)
* Uses `timer_create` and `timer_settime` with `SIGEV_THREAD_ID` targeting the main thread.
* On CPython, signal handlers are registered via `signal.signal()`.
* On MicroPython Unix, signal handlers use `ffi` and `uctypes`.
* When a timer expires, the kernel interrupts execution on the main thread and runs the Python callback immediately.

### 2. Windows `uwin32.py` (Alertable APCs)
* Uses `CreateWaitableTimerExW` and `SetWaitableTimer` with completion APCs (`TIMERAPCROUTINE`).
* When the main thread enters an **alertable wait state** (via `SleepEx(..., alertable=True)` in `multimer.win32.sleep_ms()`, or console I/O read in `python.exe -i`), the Windows kernel delivers the queued APC to the main thread.
* This provides signal-like background execution on Windows without spinning worker threads.

### 3. Microcontroller `machine.Timer` (Hardware Interrupts)
* On MicroPython boards (ESP32, RP2040, STM32, etc.), `machine.Timer` is backed directly by hardware timer peripherals and ISRs.
* Callbacks are scheduled via `micropython.schedule()`, executing safely on the main VM thread between bytecodes.

---

## MicroPython & CircuitPython Roadmap Considerations

### `micropython.exe` (Windows)
The PyDevices Windows build includes `ffi` and `uctypes`, allowing the shared
[`uwin32.py`](../utils/uwin32.py) module to call Win32 directly. `multimer.auto` therefore selects
the `win32` provider and uses alertable waitable-timer APCs, matching
`python.exe`. A custom build without `ffi` cannot import that provider and
falls through to `sdl2` (when its compiled `usdl2` module is present) or
`polling`.

Asyncio remains a build-time option. When a MicroPython build provides none of
`asyncio`, `uasyncio`, or `_asyncio`, the backend-neutral tick and synchronous
timer APIs still work, while arming `AsyncTimer` raises `ImportError`.

### CircuitPython
CircuitPython intentionally omits `machine.Timer` and low-level FFI in favor of high-level board abstractions and cooperative `asyncio`. Applications running on CircuitPython boards or the Linux port always use `multimer.AsyncTimer` or active sleep-pump loops.
