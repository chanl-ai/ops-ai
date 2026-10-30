"""A plugin package's entry point object and the `@tool` mark.

A package names its plugin in `[project.entry-points."ops_ai.plugins"]` as `name = "package:plugin"`, where
`plugin = Plugin.beside(__file__)` reads the `plugin.yaml` next to the package's `__init__.py`."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from .manifest import Manifest, read

F = TypeVar("F", bound=Callable[..., Any])
MARK = "__ops_tool__"


def tool(*, access: str) -> Callable[[F], F]:
    """Marks a function as a plugin tool with its access class; the manifest's tool entry must name the same class,
    so the class the gateway enforces is declared twice and checked to agree."""

    def mark(fn: F) -> F:
        setattr(fn, MARK, {"access": access})
        return fn

    return mark


@dataclass
class Plugin:
    manifest: Manifest
    root: Path
    _functions: dict[str, Callable[..., Any]] = field(default_factory=dict[str, Callable[..., Any]])

    @classmethod
    def beside(cls, init_file: str) -> Plugin:
        root = Path(init_file).resolve().parent
        return cls(read(root / "plugin.yaml"), root)

    def function(self, tool_name: str) -> Callable[..., Any]:
        """The Python function behind a tool, imported on first use."""
        if tool_name not in self._functions:
            t = self.manifest.tool(tool_name)
            if t is None or t.function is None:
                raise KeyError(f"{self.manifest.id} has no Python tool {tool_name}")
            module, _, name = t.function.partition(":")
            self._functions[tool_name] = getattr(importlib.import_module(module), name)
        return self._functions[tool_name]
