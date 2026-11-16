"""Every GET route of kb-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a route whose statements grow with the rows it shows, a route over its row, a route that opens a second
transaction or checks out a second connection, and agents-service asked while the request holds a transaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import mkdtemp
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_kb.store import KnowledgeStore
from ops_kb.store.knowledge import engine_for, kb_changes, kb_items, kb_runs
from ops_service_kit.settings import Settings
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check
from ops_store import isolation

from .test_list_routes import base_row, insert_rows, item_row, run_row, source_row
from .test_ownership import PLATFORM
from .test_provisioned_bases import SCOPES, person

BUDGETS = Path(__file__).parents[1] / "budgets.toml"
AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)

statement_budget = pytest.fixture(budget_check)


async def _jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def _no_keys(_key: str) -> dict[str, Any] | None:
    return None


@pytest.fixture
async def app(database_url: str) -> AsyncIterator[FastAPI]:
    """kb-service on its own engine, whose statements and transactions the request line counts, signing people in
    as platform-service does; agents-service's "used by" answers from memory."""
    engine = engine_for(database_url)
    settings = Settings(service_scopes={"platform": SCOPES})
    services = ServiceAuth(audience="kb", verifiers=service_verifiers(settings, "kb"), scopes=settings.service_scopes)
    auth = Auth(Identity(audience="kb", jwks=_jwks, introspect=_no_keys, key_cache_s=0, services=services), services)
    files = KnowledgeFiles(Path(mkdtemp(prefix="kb-files-")))
    yield create_kb_app(engine, auth=auth, files=files, agents=StaticAgents())
    await engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        yield c


def _change(source_id: str, item_id: str, n: int) -> dict[str, Any]:
    return {
        "id": f"chg_{uuid4().hex[:12]}",
        "item_id": item_id,
        "source_id": source_id,
        "title": f"Rate sheet {n}",
        "section": "Rates",
        "from_version": 1,
        "to_version": 2,
        "before": "The rate is 4.89 percent.",
        "after": "The rate is 5.19 percent.",
        "changed_by": "sync",
        "changed_at": AT + timedelta(minutes=n),
    }


@pytest.fixture
def seed_team(database_url: str, app: FastAPI) -> SeedTeam:
    """A new tenant whose team_ops holds `n` bases, `n` sources each feeding every base, and `n` runs, items and
    changes on the first source; each base is refreshed and one item failed, so health is computed for every row."""

    async def seed(n: int) -> Seeded:
        tenant = f"t_{uuid4().hex[:10]}"
        store = KnowledgeStore(engine_for(database_url))
        sources = [source_row(tenant, "team_ops", f"Source {i}") for i in range(n)]
        bases = [base_row(tenant, "team_ops", f"Base {i}") for i in range(n)]
        with isolation.scope(tenant, "team_ops"):
            for row in sources:
                await store.create_source(row, [])
            for row in bases:
                await store.create_base(row, [s["id"] for s in sources])
        first = sources[0]["id"]
        runs = await insert_rows(store.engine, tenant, "team_ops", kb_runs, *(run_row(first) for _ in range(n)))
        made = [item_row(first, f"Policy {i}", "failed" if i == 0 else "indexed") for i in range(n)]
        items = await insert_rows(store.engine, tenant, "team_ops", kb_items, *made)
        changes = [_change(first, items[0], i) for i in range(n)]
        changed = await insert_rows(store.engine, tenant, "team_ops", kb_changes, *changes)
        await store.engine.dispose()
        ids = {
            "kb_id": bases[0]["id"],
            "source_id": first,
            "run_id": runs[0],
            "item_id": items[0],
            "change_id": changed[0],
        }
        return Seeded(headers=person(tenant, "james@harborpine.example", "admin"), ids=ids)

    return seed


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
    assert await statement_budget(BUDGETS) == []
