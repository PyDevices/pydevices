# AGENTS.md

- Run tests from the repo root with `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests`. Scope one file with `-p "test_events.py"`. Don't run the audiodev tests while another process plays audio.
- Before you push a board or driver change, run `python tools/libbuild.py check` and `python tools/libbuild.py installers --check`.
- A board's `package.json` is generated from its `manifest.py` by `python tools/libbuild.py installers`. Never edit it by hand. The same goes for `palettes.toml`, `pdwidgets.toml` and the other generated file lists.
- MicroPython boards are packages (`manifest.py`); CircuitPython configs under `board_configs/cp/` are not, and take no `board_peripherals.py` unless a role needs one.
- A frozen module wins over `/lib` on MicroPython and CircuitPython, so a copied or mip-installed module never runs until you rebuild or put `/lib` first. On a source checkout the packages aren't on the path until `PYTHONPATH` (CPython) or `MICROPYPATH` (MicroPython) names `lib/`, `drivers/` and `utils/` ([bring-up guide](docs/guides/bring-up-a-board.md), [troubleshooting](docs/guides/troubleshooting.md)).
- `palettes/`, `pdwidgets/`, `appkit/` and `sayso/` publish on their own with their own versions and `AGENTS.md`; run their tests from their folders.
- Docs are MyST Markdown under `docs/`, built with `pip install -r docs/requirements.txt` and `sphinx-build -W --keep-going -b html docs _site`.
- The rules the code keeps (board-config contract, import rules, package naming) are in [CONTRIBUTING.md](CONTRIBUTING.md#rules-the-libraries-keep) and the [board contract](docs/boards/board-contract.md).
