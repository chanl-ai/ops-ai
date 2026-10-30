"""Every background process a service runs is a listed one (c-535): `background.run` with a key the registry does not
list raises when its first heartbeat is written, inside a task nobody awaits until shutdown, so the process never
runs and nothing says why. Found by the batch starter, which ran for no one until it was listed."""

from __future__ import annotations

import ast
from pathlib import Path

from ops_store.background import PROCESSES

ROOT = Path(__file__).resolve().parents[3]
SOURCES = sorted(p for p in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")) if p.is_dir())


def test_every_background_run_key_is_a_listed_process() -> None:
    listed = {p.key for p in PROCESSES}
    unlisted: list[str] = []
    for src in SOURCES:
        for path in src.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                call = node if isinstance(node, ast.Call) else None
                fn = call.func if call is not None else None
                if not (isinstance(fn, ast.Attribute) and fn.attr == "run" and isinstance(fn.value, ast.Name)):
                    continue
                if fn.value.id != "background" or not call or not call.args:
                    continue
                key = call.args[0]
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value not in listed:
                    unlisted.append(f"{path.relative_to(ROOT)}: {key.value}")
    assert unlisted == [], unlisted
