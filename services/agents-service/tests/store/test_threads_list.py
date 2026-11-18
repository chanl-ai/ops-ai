"""The threads list a page at a time in SQL (`threads_page`), by failure mode: another team's thread on the page or in
the total when the database lets every team through; a thread the reader may not read counted in the total; threads
of one update time repeated or lost between pages; metadata the SQL reads otherwise than the Python rule (a text too
long for SQL Server's JSON_VALUE, a `chat` or `owner` that is true to Python but not `true`, an all-space text, an
ownerEmail missing from the `owner` column), so a reader gains a thread. On PostgreSQL and SQL Server.
Who reads which thread is pinned through the route
(`tests/api/test_thread_readers.py`)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.graphs import graph_threads
from ops_agents.store.tenancy import tenant_tx
from ops_agents.store.thread_list import ThreadReader, threads_page
from ops_service_kit.listing import ListParams
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.team_scope import acting_as
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

AT = "2026-11-16T09:00:00.000Z"
ROOT = Path(__file__).resolve().parents[2]
TEAM, OTHER = "team_cards", "team_lending"
VERA = ThreadReader(graphs=None, chat="own", email="vera@harborpine.example", name="vera")


@pytest.fixture(scope="module", params=DATABASES)
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield Settings().database_url
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as u:
        if u is None:
            pytest.skip(NO_SQL_SERVER)
        yield u


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


async def _thread(
    e: AsyncEngine, thread_id: str, *, team: str = TEAM, meta: dict[str, Any] | None = None, column: bool = True
) -> None:
    """`column`: the `owner` column holds meta's ownerEmail, as the store writes it; False leaves it NULL."""
    meta = meta or {}
    async with tenant_tx(e) as c:
        await c.execute(
            graph_threads.insert().values(
                id=thread_id,
                graph="agent_wrapper" if meta else "refunds",
                meta=meta,
                team_id=team,
                owner=meta.get("ownerEmail") if column else None,
                created_at=AT,
                updated_at=AT,
                status="idle",
            )
        )


async def _listed(e: AsyncEngine, reader: ThreadReader = VERA, **params: Any) -> tuple[list[str], int]:
    page = await threads_page(e, ListParams(**params), reader)
    return [str(r["id"]) for r in page["data"]], page["pagination"]["total"]


async def test_the_page_and_total_hold_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        await _thread(engine, "th_mine")
    with isolation.scope(tenant, OTHER):
        await _thread(engine, "th_theirs", team=OTHER)
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with (
        isolation.tenant_wide("a test reads the threads list with every team let through", tenant_id=tenant),
        acting_as(TEAM),
    ):
        listed = await _listed(engine)
    assert listed == (["th_mine"], 1)


async def test_unreadable_threads_are_not_counted_and_equal_update_times_page_by_the_key(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        for thread_id in ("th_c", "th_a", "th_b"):
            await _thread(engine, thread_id)
        await _thread(engine, "th_vera", meta={"chat": True, "ownerEmail": "vera@harborpine.example"})
        await _thread(engine, "th_otto", meta={"chat": True, "ownerEmail": "otto@harborpine.example"})
        pages = [await _listed(engine, page=p, page_size=2) for p in (1, 2, 3)]
    # A page past the end answers the last page (`page_window`).
    assert pages == [(["th_vera", "th_c"], 4), (["th_b", "th_a"], 4), (["th_b", "th_a"], 4)]


# id -> (meta, owner column written, read by the team, by vera at chat.view own); a reader of every chat reads each.
# Each outcome is the Python rule's (`api.chat_threads.may_read_thread`) for the same row.
MALFORMED: dict[str, tuple[dict[str, Any], bool, bool, bool]] = {
    # Too long for SQL Server's JSON_VALUE: still a person's thread, never the team's.
    "th_started_for_long": ({"startedFor": "x" * 4000 + "vera@harborpine.example"}, True, False, False),
    "th_owner_long": ({"owner": "x" * 4000 + "vera"}, True, False, False),
    # `chat` and `owner` count when Python reads them as true.
    "th_chat_yes": ({"chat": "yes"}, True, False, False),
    "th_chat_two": ({"chat": 2}, True, False, False),
    "th_chat_zero_text": ({"chat": "0"}, True, False, False),
    "th_owner_object": ({"owner": {"name": "vera"}}, True, False, False),
    "th_owner_spaces": ({"owner": "  "}, True, False, False),
    "th_chat_false": ({"chat": False, "owner": ""}, True, True, True),
    "th_chat_zero": ({"chat": 0.0, "owner": {}, "startedFor": []}, True, True, True),
    # An all-space ownerEmail is set, so startedFor names nobody.
    "th_spaces_email": (
        {"ownerEmail": "   ", "startedFor": "vera@harborpine.example", "chat": True},
        True,
        False,
        False,
    ),
    "th_email_in_meta_only": ({"ownerEmail": "vera@harborpine.example"}, False, False, True),
}


async def test_malformed_or_long_metadata_is_read_as_the_python_rule_reads_it(engine: AsyncEngine, tenant: str) -> None:
    team_only = ThreadReader(graphs=None, chat="none", email="otto@harborpine.example", name="otto")
    every_chat = ThreadReader(graphs=None, chat="all", email="rita@harborpine.example", name="rita")
    with isolation.scope(tenant, TEAM):
        for thread_id, (meta, column, _, _) in MALFORMED.items():
            await _thread(engine, thread_id, meta=meta, column=column)
        seen = [sorted((await _listed(engine, reader, page_size=100))[0]) for reader in (team_only, VERA, every_chat)]
    assert seen == [
        sorted(i for i, (_, _, team, _) in MALFORMED.items() if team),
        sorted(i for i, (_, _, _, vera) in MALFORMED.items() if vera),
        sorted(MALFORMED),
    ]
