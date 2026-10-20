#!/usr/bin/env python3
"""
scripts/bundle_pyscript_assets.py — Bundle pure-Python packages for Pyodide in MkDocs.

Packages lib/ from the current repository and sibling PyDevices repositories
into docs/assets/pyscript/pydevices_bundle.zip for zero-network execution on ReadTheDocs.
"""

from pathlib import Path
import zipfile


def bundle_assets(repo_root: Path) -> Path:
    assets_dir = repo_root / "docs" / "assets" / "pyscript"
    assets_dir.mkdir(parents=True, exist_ok=True)
    bundle_zip = assets_dir / "pydevices_bundle.zip"

    # Known sibling repositories and their library paths
    workspace_root = repo_root.parent
    repos_to_bundle = ["pydevices", "palettes", "pdwidgets", "pygraphics"]

    print(f"Bundling PyDevices packages into {bundle_zip}...")
    with zipfile.ZipFile(bundle_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # First bundle current repo's lib/
        current_lib = repo_root / "lib"
        if current_lib.exists():
            for py_file in sorted(current_lib.rglob("*.py")):
                rel_path = py_file.relative_to(current_lib)
                zf.write(py_file, arcname=str(rel_path))

        # Bundle sibling repos' lib/
        for sibling_name in repos_to_bundle:
            sibling_lib = workspace_root / sibling_name / "lib"
            if sibling_lib.exists() and sibling_lib != current_lib:
                for py_file in sorted(sibling_lib.rglob("*.py")):
                    rel_path = py_file.relative_to(sibling_lib)
                    # Don't duplicate files already written
                    if str(rel_path) not in zf.namelist():
                        zf.write(py_file, arcname=str(rel_path))

    print(f"Successfully packaged {len(zf.namelist())} Python files into {bundle_zip} ({bundle_zip.stat().st_size} bytes)")
    return bundle_zip


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    bundle_assets(root)
