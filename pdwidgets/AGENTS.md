# AGENTS.md — pdwidgets

Cross-platform widget toolkit for PyDevices (`import pdwidgets`).

## Environment

- Python venv at `.venv` — `.venv/bin/python`, `.venv/bin/ruff`
- Depends on canonical PyDevices packages: `appdev`, `pygraphics`, `multimer`, `palettes`
- Source layout: `lib/pdwidgets/` (import name `pdwidgets`)

## Tests and lint

```bash
# pdwidgets is source-only and imports siblings, so PYTHONPATH is required --
# see "Import path" below. The bare unittest command fails with
# ModuleNotFoundError: No module named 'events'.
PYTHONPATH="lib:tests/stubs:../pydevices/lib:../pygraphics/lib:../palettes/lib" \
  .venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check lib tests scripts
```

Headless bench (needs pydevices-examples `board_config` on path):

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  .venv/bin/python tools/pdwidgets_bench.py
```

## Publishing

Commit `VERSION=X.Y.Z` and publish GitHub Release `vX.Y.Z`. The import and MIP
name stay `pdwidgets`; the TestPyPI distribution is `pydevices-pdwidgets`.
Procedure: [.github/docs/publishing-automation.md](https://github.com/PyDevices/.github/blob/main/docs/publishing-automation.md).

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
.venv/bin/python scripts/pdwidgets_widget_deps.py
```

## Cursor Cloud specific instructions

The Cloud Agent update script creates the repo-root `.venv` (with `ruff`).
`pdwidgets` is source-only and imports `palettes` plus product-owned
`appdev`/`multimer` and sibling `pygraphics` — none are pip-installed, so the bare
`unittest discover` / bench commands above fail without `PYTHONPATH`. In this
multi-repo workspace `palettes` and `pygraphics` come from sibling repos:

```bash
PYTHONPATH="lib:tests/stubs:../pydevices/lib:../pygraphics/lib:../palettes/lib" \
  .venv/bin/python -m unittest discover -s tests
```

Relative sibling paths, not `/agent/repos/...`: they resolve on a developer
workspace and on the cloud VM alike, since the VM's workspace root symlinks to
`/agent/repos`. This mirrors the `PYTHONPATH` that `.github/workflows/tests.yml`
builds after checking the siblings out.

The pydevices-examples repo's `.venv` also gets a `pydevices_siblings.pth` (added by the
update script) listing `palettes/lib`, `pdwidgets/lib`, and `pygraphics/lib`, so
pydevices-examples applications that import them run in the cross-interpreter matrix.
