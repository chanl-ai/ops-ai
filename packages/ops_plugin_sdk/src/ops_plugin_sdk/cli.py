"""The `ops plugin` verbs, which the one `ops` command (ops_ai.cli in the ops-ai SDK) forwards here: `ops plugin
validate <folder>` checks a plugin offline, `ops plugin test <folder>` validates it and runs its tests against its fake
system, `ops plugin install <folder>` validates it and copies it into the install's plugins folder, and `ops plugin
remove <id>` takes it out. Exit 0 done, 1 refused, failing or not installed, 2 a usage error. <folder> is the plugin's
project (with pyproject.toml) or the package folder holding plugin.yaml."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .install import install, remove
from .loader import plugin_root, project_of
from .validate import validate


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


def _install(folder: Path, into: Path) -> int:
    done, problems = install(folder, into)
    for p in problems:
        sys.stdout.write(f"REFUSED {p}\n")
    if done is None:
        return 1
    sys.stdout.write(f"INSTALLED {done.id} {done.version} in {done.folder}; restart tools-service and kb-service\n")
    return 0


def _remove(name: str, into: Path) -> int:
    gone = remove(name, into)
    if gone is None:
        sys.stdout.write(f"NOT INSTALLED {name} in {into}\n")
        return 1
    sys.stdout.write(f"REMOVED {name} from {gone}; restart tools-service and kb-service\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ops", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    area = ap.add_subparsers(dest="area", required=True)
    plugin = area.add_parser("plugin", help="build, check and install a plugin")
    verb = plugin.add_subparsers(dest="verb", required=True)
    for name, text in (
        ("validate", "check the manifest and its functions offline"),
        ("test", "validate, then run its tests"),
        ("install", "validate, then copy it into the install's plugins folder"),
        ("remove", "take a plugin out of the install's plugins folder, by its id"),
    ):
        v = verb.add_parser(name, help=text)
        v.add_argument("name" if name == "remove" else "folder", type=str if name == "remove" else Path)
        if name in ("install", "remove"):
            # The folder the services load from: the repo's plugins/ locally, OPS_PLUGINS_DIR's volume elsewhere.
            v.add_argument("--into", type=Path, default=Path("plugins"), help="the install's plugins folder")
    a = ap.parse_args(argv)
    if a.verb == "install":
        return _install(a.folder, a.into)
    if a.verb == "remove":
        return _remove(a.name, a.into)
    return _validate(a.folder) if a.verb == "validate" else _test(a.folder)


if __name__ == "__main__":
    raise SystemExit(main())
