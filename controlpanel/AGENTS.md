# AGENTS.md

- Run the tests from this folder: `python -m unittest discover -s tests -p 'test_*.py' -v`. They need LVGL for CPython (`pydevices-lvgl`), and unix MicroPython with LVGL for the other half (`PYDEVICES_MICROPYTHON`).
- `tests/panel_contract.py` is the contract and runs on either interpreter by itself; `--plant` puts back the old patch handling and must fail.
- The package imports only LVGL. Keep it that way: no appdev, no pdwidgets.
- Look LVGL names up in the generated `lvgl.pyi` before using one. A Python list can't be passed where LVGL wants a C array on CPython, which is why the pointer is a rotated image rather than an `lv.line`.
- Every LVGL callback goes through `_safe.safe`, so an exception can't stop LVGL's timers on MicroPython.
- `package.json` lists every file in `lib/controlpanel`; add a new module there too.
- Examples follow the repository's example style (see the repository's `AGENTS.md`).
