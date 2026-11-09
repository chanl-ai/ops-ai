"""Puts a plugin into an install's plugins folder, or takes it out (`opsai plugin install|remove`). The services load
every folder there at start (ops_service_kit Settings.plugins_dir), so this is the whole install: a copy of the
plugin's package folder, made only after the plugin validates."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .loader import plugin_root
from .manifest import ManifestError, read
from .validate import Problem, validate


@dataclass(frozen=True)
class Installed:
    id: str
    version: str
    folder: Path


def _ignored(_: str, names: list[str]) -> set[str]:
    return {n for n in names if n == "__pycache__" or n.endswith(".pyc")}


def install(source: Path, into: Path) -> tuple[Installed | None, list[Problem]]:
    """Validates the plugin at `source` (its package folder or its project) and copies its package folder to
    `into/<package>`, replacing an earlier copy whole; a plugin with problems is not copied."""
    root = plugin_root(source)
    if root is None:
        return None, [Problem(str(source), "no plugin.yaml here or in src/*/")]
    # A link would be followed by the copy, bringing in files from outside the plugin that nobody reviewed.
    links = [p for p in root.rglob("*") if p.is_symlink()]
    if links:
        return None, [Problem(str(p), "a symlink; a plugin holds only its own files") for p in links]
    manifest, problems = validate(root)
    if manifest is None or problems:
        return None, problems
    into.mkdir(parents=True, exist_ok=True)
    dest = into / root.name
    # Copied beside the old one first, so a copy that fails half way leaves the installed version as it was.
    staged = into / f".{root.name}.installing"
    shutil.rmtree(staged, ignore_errors=True)
    shutil.copytree(root, staged, ignore=_ignored)
    shutil.rmtree(dest, ignore_errors=True)
    staged.rename(dest)
    return Installed(manifest.id, manifest.version, dest), []


def installed(into: Path) -> dict[str, Path]:
    """Each plugin in `into` by its manifest id; a folder whose manifest does not read is listed by its folder name."""
    out: dict[str, Path] = {}
    for folder in sorted(into.iterdir()) if into.is_dir() else []:
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        root = plugin_root(folder)
        try:
            out[read(root / "plugin.yaml").id if root else folder.name] = folder
        except ManifestError:
            out[folder.name] = folder
    return out


def remove(name: str, into: Path) -> Path | None:
    """Deletes the plugin `name` (its id, or its folder's name) from `into`; None when it is not there."""
    found = installed(into)
    folder = found.get(name) or next((f for f in found.values() if f.name == name), None)
    if folder is None:
        return None
    shutil.rmtree(folder)
    return folder
