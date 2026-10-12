"""Rule 15 fails on each thing it guards: a driver imported outside a store and off the allowlist, a listed file that
no longer imports one, and a header that disagrees with the list."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_standards  # pyright: ignore[reportMissingImports]


def test_a_store_is_a_package_a_module_or_a_database_package() -> None:
    assert check_standards.is_store(Path("services/x/src/ops_x/store/things.py"))  # pyright: ignore[reportUnknownMemberType]
    assert check_standards.is_store(Path("services/x/src/ops_x/store.py"))  # pyright: ignore[reportUnknownMemberType]
    assert check_standards.is_store(Path("packages/ops_store/src/ops_store/conformance.py"))  # pyright: ignore[reportUnknownMemberType]
    assert not check_standards.is_store(Path("services/x/src/ops_x/api/routes.py"))  # pyright: ignore[reportUnknownMemberType]


def test_each_guarded_change_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allow = tmp_path / "store-allowlist.txt"
    allow.write_text("# 2 files import a database driver\nlisted_and_clean.py\n")
    monkeypatch.setattr(check_standards, "ALLOWLIST", allow)
    assert check_standards.imports_driver(ast.parse("from sqlalchemy import select")) == 1  # pyright: ignore[reportUnknownMemberType]
    assert check_standards.imports_driver(ast.parse("import json")) is None  # pyright: ignore[reportUnknownMemberType]
    out: list[str] = []
    check_standards.check_store_door({"new_offender.py": 3}, out)  # pyright: ignore[reportUnknownMemberType]
    found = "\n".join(out)
    assert "new_offender.py:3 rule 15: database driver imported outside a store" in found
    assert "listed_and_clean.py rule 15: on store-allowlist.txt but no longer imports a driver" in found
    assert "the header says 2 and the file lists 1" in found
