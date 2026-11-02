"""Finds the installed plugins and validates each, as tools-service does at start (plugin-architecture.html section 03).

A plugin whose import raises, or whose manifest fails `validate`, is recorded as failed with why and left out; the
service starts without it, so one broken package never takes every team's tools down."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any

from .plugin import Plugin
from .validate import check

GROUP = "ops_ai.plugins"


@dataclass(frozen=True)
class Loaded:
    name: str
    plugin: Plugin | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.plugin is not None


def plugin_root(folder: Path) -> Path | None:
    """The folder holding plugin.yaml: `folder` itself, or the one package under its src/."""
    if (folder / "plugin.yaml").is_file():
        return folder
    found = sorted((folder / "src").glob("*/plugin.yaml")) if (folder / "src").is_dir() else []
    return found[0].parent if len(found) == 1 else None


def project_of(root: Path) -> Path:
    """The project folder above a src/<package> layout, else the package folder itself."""
    return root.parent.parent if root.parent.name == "src" else root


def _from_folder(folder: Path) -> Any:
    """A package folder's `plugin` object, imported by the folder's name with its parent on the path."""
    sys.path.insert(0, str(folder.parent))
    try:
        return importlib.import_module(folder.name).plugin
    finally:
        sys.path.remove(str(folder.parent))


def discover(found: Iterable[EntryPoint] | None = None, folders: Iterable[str] = ()) -> list[Loaded]:
    """Every entry point in the `ops_ai.plugins` group, then each folder in `folders` (the install's plugins folder,
    then a developer's plugin paths), loaded or failed; `found` replaces the installed set (tests)."""
    out: list[Loaded] = []
    seen: set[str] = set()
    loaders: list[tuple[str, Callable[[], Any], str]] = [
        (ep.name, ep.load, ep.value)
        for ep in sorted(found if found is not None else entry_points(group=GROUP), key=lambda e: e.name)
    ]
    for f in folders:
        # A plugin dropped into the plugins folder may be its package folder or its whole project (src/<package>);
        # a folder with neither is still tried, so its failure is reported under its own name.
        given = Path(f).resolve()
        folder = plugin_root(given) or given
        loaders.append((folder.name, lambda folder=folder: _from_folder(folder), str(folder)))
    for name, load, where in loaders:
        try:
            obj = load()
        except Exception as e:  # any import failure is the plugin's, and is reported, never raised
            out.append(Loaded(name, None, f"import failed: {type(e).__name__}: {e}"))
            continue
        if not isinstance(obj, Plugin):
            out.append(Loaded(name, None, f"{where} is not an ops_plugin_sdk.Plugin"))
            continue
        problems = check(obj.manifest, obj.root)
        if problems:
            out.append(Loaded(name, None, "; ".join(str(p) for p in problems)))
            continue
        if obj.manifest.id in seen:
            out.append(Loaded(name, None, f"{obj.manifest.id} is installed twice"))
            continue
        seen.add(obj.manifest.id)
        out.append(Loaded(name, obj, None))
    return out
