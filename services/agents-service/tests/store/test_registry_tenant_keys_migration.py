"""Migration 0108 puts the tenant in the workflow, widget, deployment and channel keys, by failure mode, on a scratch
database at 0107: a tenant whose thread runs a seeded `local` workflow is left without its own copy (so its pinned
digest would not resolve once the policies hold), a tenant with no reference gets one anyway, a second run copies
twice; a version written under a parent of another tenant keeps the wrong tenant and fails the composite key; the down
path leaves the copies behind, or restores install-wide keys while two tenants hold one id."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL

from .test_registry_tenant_migration import AT, insert, migrate
from .test_registry_tenant_preflight import alembic, scratch_at, sql, thread

BEFORE = "0107_system_reads_agent_pointers"
HEAD = "0108_registry_tenant_keys"


@pytest.fixture
def scratch() -> Iterator[URL]:
    url, drop = scratch_at(BEFORE)
    try:
        yield url
    finally:
        drop()


def _workflow(tenant: str, workflow_id: str) -> list[sa.Insert]:
    return [
        insert(
            "registry_workflows",
            tenant_id=tenant,
            id=workflow_id,
            team_id="team_ops",
            name="Levy",
            description="",
            trigger="manual",
            status="live",
            published_version=1,
            created_at=AT,
            updated_at=AT,
        ),
        insert(
            "registry_workflow_versions",
            tenant_id=tenant,
            workflow_id=workflow_id,
            version=1,
            graph="{}",
            note="",
            changes="[]",
            published_at=AT,
            published_by="seed",
        ),
        insert(
            "graph_versions",
            tenant_id=tenant,
            name=workflow_id,
            version=1,
            digest=f"dg-{workflow_id}",
            definition="{}",
            created_at=AT,
        ),
    ]


def _rows(url: URL, table: str, *columns: str) -> list[tuple[str, ...]]:
    t = sa.table(table, *(sa.column(c, sa.String) for c in columns))
    (rows,) = asyncio.run(sql(url, sa.select(*t.c).order_by(*t.c)))
    return [tuple(str(v) for v in r) for r in rows]


def test_a_tenant_on_a_local_workflow_gets_one_copy_and_a_stray_version_follows_its_parent(scratch: URL) -> None:
    asyncio.run(
        sql(
            scratch,
            *_workflow("local", "wf_levy"),
            thread("t-pine", "team_cards", "wf_levy"),
            thread("local", "team_ops", "wf_levy"),
            # A tenant with a thread on something else gets no copy.
            thread("t-harbor", "team_cards", "chat"),
            insert(
                "registry_widgets",
                tenant_id="t-pine",
                id="wd_card",
                team_id="team_cards",
                name="Card",
                version=1,
                created_at=AT,
                updated_at=AT,
                updated_by="maya@x.example",
            ),
            # Written as `local` under t-pine's widget before the stores named the caller's tenant.
            insert(
                "registry_widget_versions",
                tenant_id="local",
                widget_id="wd_card",
                version=1,
                content="{}",
                digest="dg",
                changes="[]",
                saved_at=AT,
                saved_by="maya@x.example",
            ),
        )
    )
    migrate(scratch, "upgrade", HEAD)
    migrate(scratch, "downgrade", BEFORE)
    migrate(scratch, "upgrade", HEAD)
    alembic(scratch, "stamp", BEFORE)
    migrate(scratch, "upgrade", HEAD)
    assert _rows(scratch, "registry_workflows", "tenant_id", "id") == [("local", "wf_levy"), ("t-pine", "wf_levy")]
    assert _rows(scratch, "registry_workflow_versions", "tenant_id", "workflow_id", "version") == [
        ("local", "wf_levy", "1"),
        ("t-pine", "wf_levy", "1"),
    ]
    assert _rows(scratch, "graph_versions", "tenant_id", "name", "version", "digest") == [
        ("local", "wf_levy", "1", "dg-wf_levy"),
        ("t-pine", "wf_levy", "1", "dg-wf_levy"),
    ]
    assert _rows(scratch, "registry_widget_versions", "tenant_id", "widget_id") == [("t-pine", "wd_card")]


def test_the_down_path_removes_the_copies_and_refuses_with_a_count_while_two_tenants_hold_one_id(
    scratch: URL,
) -> None:
    asyncio.run(sql(scratch, *_workflow("local", "wf_levy"), thread("t-pine", "team_cards", "wf_levy")))
    migrate(scratch, "upgrade", HEAD)
    deployment = "INSERT INTO deployments (tenant_id, id, graph, channel, created_at, team_id) VALUES "
    asyncio.run(
        sql(
            scratch,
            (deployment + "('t-pine', 'dep_mail', 'g', 'email', :at, 'team_a')", {"at": AT}),
            (deployment + "('t-harbor', 'dep_mail', 'g', 'email', :at, 'team_b')", {"at": AT}),
        )
    )
    done = alembic(scratch, "downgrade", BEFORE)
    assert done.returncode != 0
    assert "held by more than one tenant, so the install-wide keys would fail: 1 deployment ids" in done.stderr
    asyncio.run(sql(scratch, ("DELETE FROM deployments WHERE tenant_id = 't-harbor'", {})))
    migrate(scratch, "downgrade", BEFORE)
    assert _rows(scratch, "registry_workflows", "tenant_id", "id") == [("local", "wf_levy")]


@pytest.mark.parametrize(("source", "user"), [("local", "t-pine"), ("t-pine", "local")])
def test_a_copy_carries_its_sources_versions_and_the_down_path_removes_only_the_copy(
    scratch: URL, source: str, user: str
) -> None:
    """Whichever tenant holds the workflow, the copy gets its versions and graph versions; going down deletes the copy
    and its graph versions, never the source's, and the chain then steps below 0106 without a duplicate."""
    asyncio.run(
        sql(
            scratch,
            *_workflow(source, "wf_levy"),
            thread(source, "team_cards", "wf_levy"),
            thread(user, "team_cards", "wf_levy"),
        )
    )
    migrate(scratch, "upgrade", HEAD)
    both = sorted([(source, "wf_levy", "1"), (user, "wf_levy", "1")])
    assert _rows(scratch, "registry_workflow_versions", "tenant_id", "workflow_id", "version") == both
    assert _rows(scratch, "graph_versions", "tenant_id", "name", "version") == both
    migrate(scratch, "downgrade", BEFORE)
    assert _rows(scratch, "registry_workflows", "tenant_id", "id") == [(source, "wf_levy")]
    assert _rows(scratch, "registry_workflow_versions", "tenant_id", "workflow_id", "version") == [
        (source, "wf_levy", "1")
    ]
    assert _rows(scratch, "graph_versions", "tenant_id", "name", "version") == [(source, "wf_levy", "1")]
    migrate(scratch, "downgrade", "0105_thread_owner_column")
