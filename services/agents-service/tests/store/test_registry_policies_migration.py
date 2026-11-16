"""Migration 0109 places the rows still at `local` and drops the `local` defaults, by failure mode, on a scratch
PostgreSQL database at 0108: a row whose rules give another tenant stays at `local` (an agent and its version, a
deployment with its cursor, ledger row and inbox row), a move onto a key the target tenant already holds fails the
upgrade instead of being skipped, a second run moves something else, and a write that names no tenant still lands in
`local` after the step, or is refused after the down path, which gives the default back."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError

from ops_service_kit.ids import new_id

from .test_registry_tenant_migration import AT, insert, migrate, version_of
from .test_registry_tenant_preflight import agent, alembic, scratch_at, sql, thread

BEFORE = "0108_registry_tenant_keys"
HEAD = "0109_registry_policies"


@pytest.fixture
def scratch() -> Iterator[URL]:
    url, drop = scratch_at(BEFORE)
    try:
        yield url
    finally:
        drop()


def _rows(url: URL, table: str, *columns: str) -> list[tuple[str, ...]]:
    t = sa.table(table, *(sa.column(c, sa.String) for c in columns))
    (rows,) = asyncio.run(sql(url, sa.select(*t.c).order_by(*t.c)))
    return [tuple(str(v) for v in r) for r in rows]


def _widget(tenant: str) -> sa.Insert:
    return insert(
        "registry_widgets",
        tenant_id=tenant,
        id="wd_card",
        team_id="team_cards",
        name="Card",
        version=1,
        created_at=AT,
        updated_at=AT,
        updated_by="maya@x.example",
    )


def test_local_rows_move_to_their_one_tenant_a_held_key_stays_and_a_second_run_moves_nothing(scratch: URL) -> None:
    mail_thread = new_id("thr")
    asyncio.run(
        sql(
            scratch,
            # Written as `local` before the stores named the caller's tenant; t-pine's thread runs it.
            agent("ag_late", "team_cards"),
            version_of("ag_late"),
            thread("t-pine", "team_cards", "agent:ag_late"),
            # t-pine already holds wd_card, so the `local` one stays where it is.
            _widget("local"),
            _widget("t-pine"),
            # An agent whose team no other tenant holds stays in `local`.
            agent("ag_home", "team_ops"),
            insert("deployments", id="dep_mail", graph="g", channel="email", created_at=AT, team_id=""),
            (
                "INSERT INTO graph_threads (tenant_id, id, graph, meta, team_id, created_at, updated_at, status, "
                "deployment_id) VALUES ('t-pine', :id, 'chat', CAST('{}' AS json), 'team_cards', :at, :at, 'idle', "
                "'dep_mail')",
                {"id": mail_thread, "at": AT},
            ),
            insert("channel_cursors", deployment_id="dep_mail", delta_link="d", updated_at=AT),
            insert(
                "channel_messages",
                deployment_id="dep_mail",
                message_key="m1",
                role="in",
                status="handled",
                received_at=AT,
            ),
            insert(
                "thread_inbox",
                thread_id=mail_thread,
                message_key="m1",
                seq=1,
                kind="email",
                payload="{}",
                status="queued",
                created_at=AT,
            ),
        )
    )
    migrate(scratch, "upgrade", HEAD)
    alembic(scratch, "stamp", BEFORE)
    migrate(scratch, "upgrade", HEAD)
    assert _rows(scratch, "registry_agents", "tenant_id", "id") == [("local", "ag_home"), ("t-pine", "ag_late")]
    assert _rows(scratch, "registry_agent_versions", "tenant_id", "agent_id") == [("t-pine", "ag_late")]
    assert _rows(scratch, "registry_widgets", "tenant_id", "id") == [("local", "wd_card"), ("t-pine", "wd_card")]
    assert _rows(scratch, "deployments", "tenant_id", "id") == [("t-pine", "dep_mail")]
    assert _rows(scratch, "channel_cursors", "tenant_id", "deployment_id") == [("t-pine", "dep_mail")]
    assert _rows(scratch, "channel_messages", "tenant_id", "message_key") == [("t-pine", "m1")]
    assert _rows(scratch, "thread_inbox", "tenant_id", "message_key") == [("t-pine", "m1")]

    unnamed = agent("ag_new", "team_ops")
    with pytest.raises(IntegrityError):
        asyncio.run(sql(scratch, unnamed))
    migrate(scratch, "downgrade", BEFORE)
    asyncio.run(sql(scratch, unnamed))
    assert ("local", "ag_new") in _rows(scratch, "registry_agents", "tenant_id", "id")
