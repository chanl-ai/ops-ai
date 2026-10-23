"""The case type store with the acting team's seeded case types in place (c-291; per team, c-507), seeded on the
team's first read in this process as the task types are (task_type_seeds.py). Both the API and the worker's Open case
step read types through it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ops_store.team_scope import acting_team

from ..case_fields import specs_of
from ..store.case_types import CaseTypeStore
from ..store.engine import AsyncEngine
from ..store.tenancy import current_tenant
from .deps import Runtime

SEED_FILE = Path(__file__).resolve().parents[3] / "seed" / "case_types.json"
# Teams whose seeds this process has checked, per database and tenant; a restart checks again, which inserts nothing
# new.
_seeded: set[tuple[int, str, str | None]] = set()


def seeds() -> list[dict[str, Any]]:
    """The general case types every tenant reads, each checked as a team's would be."""
    out = cast(list[dict[str, Any]], json.loads(SEED_FILE.read_text()))
    for s in out:
        specs_of(s["fields"])
    return out


async def seeded_case_types(db: AsyncEngine, team: str | None = None) -> CaseTypeStore:
    """`team`: the team of the record being served (a case, a run's step), when it is not the acting team."""
    store = CaseTypeStore(db, team)
    key = (id(db), current_tenant(), team or acting_team())
    if key not in _seeded:
        await store.ensure_seeds(seeds())
        _seeded.add(key)
    return store


async def case_type_store(rt: Runtime) -> CaseTypeStore:
    return await seeded_case_types(rt.db)
