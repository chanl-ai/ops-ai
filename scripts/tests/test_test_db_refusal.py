"""test_db.py makes and drops the databases of test runs; a name that is a stack's database is never one of them."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def test_no_stack_database_is_taken_for_a_test_database() -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import test_db  # noqa: PLC0415  # the script's own module, found beside it
    finally:
        sys.path.remove(str(SCRIPTS))
    # Port 1: a refusal fires before any connection, and a miss would fail on the connection instead.
    for name in ("ops_runtime", "ops_runtime_400"):
        url = f"postgresql+asyncpg://ops:ops@localhost:1/{name}"
        for call in (test_db.create(url), test_db.clone(url, None)):
            with pytest.raises(SystemExit, match="refusing"):
                asyncio.run(call)
