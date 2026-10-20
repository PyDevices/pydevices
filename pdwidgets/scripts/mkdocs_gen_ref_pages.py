"""Generate mkdocstrings API reference stubs and navigation for pdwidgets.

Walks ``lib/pdwidgets/``. Skips private modules and generated ``icons/`` pages.
"""

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()
root = Path(__file__).parent.parent
lib = root / "lib"
reference = Path("reference")
SKIP_DIR_NAMES = {"icons", "__pycache__"}

for path in sorted((lib / "pdwidgets").rglob("*.py")):
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        continue
    if path.name.startswith("_") and path.name != "__init__.py":
        continue
    module_path = path.relative_to(lib).with_suffix("")
    doc_path = module_path.with_suffix(".md")
    full_doc_path = reference / doc_path

    parts = tuple(module_path.parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")
    if not parts or parts[-1] == "__main__" or any(part.startswith("_") for part in parts):
        continue

    nav[parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        ident = ".".join(parts)
        fd.write(f"::: {ident}\n")

    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))

with mkdocs_gen_files.open("reference/summary.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
