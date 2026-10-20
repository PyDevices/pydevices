# AGENTS.md — pdwidgets

Cross-platform widget toolkit for PyDevices (`import pdwidgets`).

## Environment

- A folder of the pydevices repository; run the commands below from here
  (`pdwidgets/`)
- Depends on `appdev` and `multimer` (pydevices' `lib/`), `palettes`
  (`../palettes`) and `pygraphics` (its own repository)
- Source layout: `lib/pdwidgets/` (import name `pdwidgets`)

## Tests and lint

```bash
# pdwidgets is source-only and imports siblings, so PYTHONPATH is required --
# see "Import path" below. The bare unittest command fails with
# ModuleNotFoundError: No module named 'events'.
PYTHONPATH="lib:tests/stubs:../lib:../palettes/lib:$PYGRAPHICS/lib" \
  python -m unittest discover -s tests
ruff check lib tests scripts
```

Headless bench (needs pydevices-examples `board_config` on path):

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  python tools/pdwidgets_bench.py
```

## Publishing

pdwidgets has its own version, in `VERSION` here, apart from the pydevices
release. A pull request that changes `VERSION` (and `CHANGELOG.md`) and merges
tags `pdwidgets-vX.Y.Z` and publishes `pydevices-pdwidgets` to TestPyPI from
the pydevices repository's release chain. The import and mip name stay
`pdwidgets`.

## Widget API (agent contract)

- **Content kwargs**: Labels use `value=`; buttons use `label=`. There is no
  `text=` kwarg and no class-name aliases (`ListTile`, `Tag`, `TabBar`, etc.).
- **`radius`**: Stored on every `Widget` (default `0`). Rounded faces (`Button`,
  `Card`, `Chip`, …) read `self.radius`; the base `draw()` fill ignores it.
- **Detach / empty**: `widget.remove()` detaches from the parent;
  `widget.clear()` removes all children. Both use `remove_child` under the hood.
  Hiding without detaching: `widget.hide()` or `widget.visible = False`.
- **Event callbacks**: `add_event_cb` invokes
  `callback(data_or_sender, event)` — sender/data first, event second. Default
  `data` is the widget that registered the callback.

## Widget dependency graph

Regenerate after editing widgets:

```bash
python scripts/pdwidgets_widget_deps.py
```

## Import path

`pdwidgets` is source-only and imports `palettes`, `appdev`, `multimer` and
`pygraphics`, none of them pip-installed in CI, so the bare `unittest
discover` and bench commands fail without `PYTHONPATH`. `$PYGRAPHICS` above
is a checkout of [pygraphics](https://github.com/PyDevices/pygraphics); the
`pdwidgets` workflow in `.github/workflows/` checks it out the same way.
