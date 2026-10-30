"""Each migration chain's schema as SQLAlchemy metadata: every MetaData its service's store package defines, found by
importing that package, so no list of tables is kept by hand. Generated DDL for a database without the chains (SQL
Server) compiles from this, and test_model_parity.py holds it equal to what the chains build on PostgreSQL.

    from models import chain_metadata, EXCLUDED
    chain_metadata("files")   # [ops_files.store.metadata]
"""

from __future__ import annotations

import importlib
import pkgutil
from functools import cache
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

CHAINS_FILE = Path(__file__).resolve().parents[1] / "images" / "chains"
# Packages a chain migrates besides its own service's store: agents-service's chain holds the workflow engine's tables.
HOSTED: dict[str, tuple[str, ...]] = {"agents": ("ops_engine.store", "ops_checkpointer.tables")}
# Tables a chain creates that no metadata defines yet, and why. None today.
EXCLUDED: dict[str, frozenset[str]] = {}


def chains() -> list[str]:
    lines = CHAINS_FILE.read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def _modules(package: str) -> list[ModuleType]:
    root = importlib.import_module(package)
    found = [root]
    if hasattr(root, "__path__"):
        found += [importlib.import_module(m.name) for m in pkgutil.walk_packages(root.__path__, f"{package}.")]
    return found


@cache
def chain_metadata(chain: str) -> tuple[sa.MetaData, ...]:
    """Every MetaData reachable from the chain's store packages, each once."""
    seen: dict[int, sa.MetaData] = {}
    for package in (f"ops_{chain}.store", *HOSTED.get(chain, ())):
        for module in _modules(package):
            for value in vars(module).values():
                if isinstance(value, sa.MetaData):
                    seen.setdefault(id(value), value)
                elif isinstance(value, sa.Table):
                    seen.setdefault(id(value.metadata), value.metadata)
    return tuple(seen.values())
