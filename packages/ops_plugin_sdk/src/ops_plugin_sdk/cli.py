"""`ops`, the one command line: `ops plugin validate <folder>` checks a plugin offline, `ops plugin test <folder>`
validates it and runs its tests against its fake system. Exit 0 valid or passing, 1 refused or failing, 2 a usage
error. <folder> is the plugin's project (with pyproject.toml) or the package folder holding plugin.yaml."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .validate import validate


def plugin_root(folder: Path) -> Path | None:
    """The folder holding plugin.yaml: `folder` itself, or the one package under its src/."""
    if (folder / "plugin.yaml").is_file():
        return folder
    found = sorted((folder / "src").glob("*/plugin.yaml")) if (folder / "src").is_dir() else []
    return found[0].parent if len(found) == 1 else None


def project_of(root: Path) -> Path:
    """The project folder above a src/<package> layout, else the package folder itself."""
    return root.parent.parent if root.parent.name == "src" else root


def _validate(folder: Path) -> int:
    root = plugin_root(folder)
    if root is None:
        sys.stderr.write(f"ops plugin: no plugin.yaml in {folder} or {folder}/src/*/\n")
        return 2
    manifest, problems = validate(root)
    for p in problems:
        sys.stdout.write(f"REFUSED {p}\n")
    if manifest is not None and not problems:
        sys.stdout.write(
            f"OK {manifest.id} {manifest.version}: {len(manifest.tools)} tools, "
            f"{len(manifest.knowledge_sources)} knowledge sources, {len(manifest.templates)} templates\n"
        )
    return 1 if problems else 0


def _test(folder: Path) -> int:
    code = _validate(folder)
    if code:
        return code
    root = plugin_root(folder)
    assert root is not None
    # The plugin's own pytest settings (testpaths) say where its tests are, as for any project.
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    # A plugin in its own repository (ops-ai-plugins) is not installed where the kit runs: its src/ goes on pytest's
    # path so its tests import it as tools-service will.
    if root.parent.name == "src":
        argv += ["-o", f"pythonpath={root.parent.resolve()}"]
    return subprocess.run(argv, cwd=project_of(root), check=False).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ops", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    area = ap.add_subparsers(dest="area", required=True)
    plugin = area.add_parser("plugin", help="build and check a plugin")
    verb = plugin.add_subparsers(dest="verb", required=True)
    for name, text in (
        ("validate", "check the manifest and its functions offline"),
        ("test", "validate, then run its tests"),
    ):
        v = verb.add_parser(name, help=text)
        v.add_argument("folder", type=Path)
    a = ap.parse_args(argv)
    return _validate(a.folder) if a.verb == "validate" else _test(a.folder)


if __name__ == "__main__":
    raise SystemExit(main())
