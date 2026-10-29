# AGENTS.md

- Run from `pdwidgets/`. It imports `appdev`, `multimer`, `palettes` and `pygraphics` from source, so the bare test command fails with `No module named 'events'` unless they're installed. Put them on the path, with a pygraphics checkout at `$PYGRAPHICS`: `PYTHONPATH="lib:tests/stubs:../lib:../palettes/lib:$PYGRAPHICS/lib" python -m unittest discover -s tests`, then `ruff check lib tests scripts`.
- After you add or change a widget, run `python scripts/pdwidgets_widget_deps.py` to regenerate `lib/pdwidgets/widget-dependencies.md`. `lib/pdwidgets/icons/` and `pdwidgets.toml` are generated too; don't edit them by hand.
- A `Label` takes `value=` and a `Button` takes `label=`. There is no `text=`. Callbacks are `callback(sender, event)`.
- `pdwidgets` has its own version in `VERSION`, apart from the pydevices release; see [CONTRIBUTING.md](CONTRIBUTING.md#release) and its widget conventions.
- `tests/test_doc_examples.py` checks the Python blocks in the docs against the package, so a renamed argument fails there.
- Examples follow the style in the [repo's AGENTS.md](../AGENTS.md): REUSE licence header, a docstring ending `Needs:`, `Run it:`, `Tested on:`, a settings block, a comment above each step, pygraphics rather than `framebuf`.
