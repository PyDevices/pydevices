# AGENTS.md

- Run the tests from this folder: `python -m unittest discover -s tests -p 'test_*.py' -v`. They need LVGL, audiodsp, audioinstruments (with its `panel` module) and controlpanel for CPython, and unix MicroPython with LVGL and audiodsp for the other half (`PYDEVICES_MICROPYTHON`). `SYNTHSTATION_PATH` puts folders in front of the path, for a checkout of audioinstruments.
- `tests/station_check.py` drives the whole app through every instrument on either interpreter by itself; `--shots DIR` saves the picker and the first panel as raw RGB565 frames.
- `main(scope)` does nothing at import time, and `import synthstation` imports nothing else: keep it that way, so the app's modules load only when it opens.
- A timer tick on a board lands between the bytecodes of whatever the app is doing. Anything a tick and the foreground both touch needs the `loading` or `_filling` guard.
- `package.json` lists every file in `lib/synthstation`; add a new module there too.
- Examples follow the repository's example style (see the repository's `AGENTS.md`).
