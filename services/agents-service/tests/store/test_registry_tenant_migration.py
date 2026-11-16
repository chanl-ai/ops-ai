"""Migration 0106 gives the registry, graph version and channel tables their tenant, by failure mode, each on a scratch
database at 0105 holding two tenants' rows: a row lands in the wrong tenant (a direct reference must beat the team, a
child must follow its parent, a channel row its thread or deployment); outside dev a row with no one tenant is placed
anyway instead of stopping the upgrade, or `local` beside one other tenant stops it; in dev such rows do not fall to
`local`; the down path leaves duplicates under an install-wide key, or a second run places rows differently."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL

from ops_service_kit.ids import now_iso

from .test_registry_tenant_preflight import agent, alembic, scratch_at, sql, thread

BEFORE = "0105_thread_owner_column"
HEAD = "0106_registry_tenant_columns"
AT = now_iso()


@pytest.fixture
def scratch() -> Iterator[URL]:
    url, drop = scratch_at(BEFORE)
    try:
        yield url
    finally:
        drop()


def insert(table: str, **values: Any) -> sa.Insert:
    columns = (sa.column(k, sa.JSON if k in JSON else None) for k in values)
    return sa.insert(sa.table(table, *columns)).values(
        **{k: json.loads(v) if k in JSON else v for k, v in values.items()}
    )


JSON = {"spec", "changes", "definition", "payload", "body", "meta"}


def version_of(agent_id: str) -> sa.Insert:
    return insert(
        "registry_agent_versions",
        agent_id=agent_id,
        version=1,
        spec="{}",
        digest=f"d-{agent_id}",
        note="",
        changes="[]",
        saved_at=AT,
        saved_by="seed",
    )


def default(tenant: str, team: str, agent_id: str) -> sa.Insert:
    return insert(
        "team_default_agents",
        tenant_id=tenant,
        team_id=team,
        agent_id=agent_id,
        updated_by="maya@x.example",
        updated_at=AT,
    )


def tenants(url: URL, table: str, key: str) -> dict[str, str]:
    t = sa.table(table, sa.column(key), sa.column("tenant_id"))
    (rows,) = asyncio.run(sql(url, sa.select(t.c[key], t.c.tenant_id)))
    return {str(k): str(t) for k, t in rows}


def outside_dev(environment: str) -> dict[str, str]:
    """The settings a service outside dev starts with: no dev sign-in."""
    return {"OPS_ENVIRONMENT": environment} | ({} if environment == "dev" else {"OPS_AUTH_MODE": "platform"})


def migrate(url: URL, *args: str, environment: str = "dev") -> str:
    done = alembic(url, *args, **outside_dev(environment))
    assert done.returncode == 0, done.stderr[-3000:]
    return done.stderr


def test_each_row_takes_its_reference_then_its_team_then_local_and_a_second_run_places_it_the_same(
    scratch: URL,
) -> None:
    asyncio.run(
        sql(
            scratch,
            # team_claims is t-harbor's; ag_direct is still t-pine's, since t-pine named it as a team's default.
            thread("t-harbor", "team_claims"),
            agent("ag_team", "team_claims"),
            version_of("ag_team"),
            agent("ag_direct", "team_claims"),
            default("t-pine", "team_cards", "ag_direct"),
            # team_payroll is in no tenant; team_lending in two; ag_shared is chatted with from two: all local in dev.
            agent("ag_unmapped", "team_payroll"),
            thread("t-harbor", "team_lending"),
            thread("t-pine", "team_lending"),
            agent("ag_two", "team_lending"),
            agent("ag_shared", "team_claims"),
            thread("t-harbor", "team_other", "agent:ag_shared"),
            thread("t-pine", "team_other", "agent:ag_shared"),
            # A workflow t-pine's thread runs, its published graph, and a deployment with no team that t-pine's thread
            # came through, with a message, a cursor and an inbox row.
            insert(
                "registry_workflows",
                id="wf_levy",
                team_id="team_claims",
                name="Levy",
                description="",
                trigger="manual",
                status="live",
                created_at=AT,
                updated_at=AT,
            ),
            insert("graph_versions", name="wf_levy", version=1, digest="dg-levy", definition="{}", created_at=AT),
            insert(
                "graph_threads",
                tenant_id="t-pine",
                id="thr_mail",
                graph="wf_levy",
                meta="{}",
                team_id="team_cards",
                created_at=AT,
                updated_at=AT,
                status="idle",
                deployment_id="dep_mail",
            ),
            insert("deployments", id="dep_mail", graph="wf_levy", channel="email", created_at=AT, team_id=""),
            insert(
                "channel_messages",
                deployment_id="dep_mail",
                message_key="m1",
                thread_id="thr_mail",
                role="in",
                status="handled",
                received_at=AT,
            ),
            insert("channel_cursors", deployment_id="dep_mail", delta_link="d", updated_at=AT),
            insert(
                "thread_inbox",
                thread_id="thr_mail",
                message_key="m1",
                seq=1,
                kind="mail",
                payload="{}",
                status="queued",
                created_at=AT,
            ),
            insert(
                "registry_publish_requests",
                tenant_id="t-pine",
                id="WFP-1",
                kind="workflow",
                subject_id="wf_levy",
                version=1,
                status="pending",
                note="",
                requested_by="maya@x.example",
                created_at=AT,
                body="{}",
            ),
        )
    )
    expected = {
        "registry_agents": {
            "ag_team": "t-harbor",
            "ag_direct": "t-pine",
            "ag_unmapped": "local",
            "ag_two": "local",
            "ag_shared": "local",
        },
        "registry_agent_versions": {"ag_team": "t-harbor"},
        "registry_workflows": {"wf_levy": "t-pine"},
        "graph_versions": {"wf_levy": "t-pine"},
        "deployments": {"dep_mail": "t-pine"},
        "channel_messages": {"m1": "t-pine"},
        "channel_cursors": {"dep_mail": "t-pine"},
        "thread_inbox": {"m1": "t-pine"},
    }
    keys = {"registry_agent_versions": "agent_id", "graph_versions": "name", "channel_cursors": "deployment_id"}
    keys |= {"channel_messages": "message_key", "thread_inbox": "message_key"}

    def placed() -> dict[str, dict[str, str]]:
        return {table: tenants(scratch, table, keys.get(table, "id")) for table in expected}

    migrate(scratch, "upgrade", HEAD)
    assert placed() == expected
    (rows,) = asyncio.run(
        sql(
            scratch,
            (
                "SELECT d.team_id, r.team_id FROM deployments d, registry_publish_requests r "
                "WHERE d.id = 'dep_mail' AND r.id = 'WFP-1'",
                {},
            ),
        )
    )
    assert rows == [("team_cards", "team_claims")]
    migrate(scratch, "downgrade", BEFORE)
    migrate(scratch, "upgrade", HEAD)
    assert placed() == expected


def test_outside_dev_it_stops_on_a_team_or_record_with_no_one_tenant_and_names_each(scratch: URL) -> None:
    asyncio.run(
        sql(
            scratch,
            agent("ag_unmapped", "team_payroll"),
            thread("t-harbor", "team_lending"),
            thread("t-pine", "team_lending"),
            agent("ag_two", "team_lending"),
            thread("t-harbor", "team_lending", "agent:ag_shared"),
            thread("t-pine", "team_lending", "agent:ag_shared"),
            agent("ag_shared", "team_lending"),
        )
    )
    done = alembic(scratch, "upgrade", HEAD, **outside_dev("test"))
    assert done.returncode != 0
    assert (
        "no tenant: team team_payroll holds 1 row(s) in registry_agents\n"
        "two tenants: team team_lending is in 2 tenants: t-harbor, t-pine\n"
        "two tenants: registry_agents ag_shared is referenced from 2 tenants: t-harbor, t-pine"
    ) in done.stderr
    (rows,) = asyncio.run(sql(scratch, ("SELECT version_num FROM alembic_version", {})))
    assert rows == [(BEFORE,)]


def test_outside_dev_local_beside_one_other_tenant_gives_way_to_it(scratch: URL) -> None:
    asyncio.run(
        sql(scratch, thread("local", "team_cards"), thread("t-pine", "team_cards"), agent("ag_cards", "team_cards"))
    )
    migrate(scratch, "upgrade", HEAD, environment="test")
    assert tenants(scratch, "registry_agents", "id") == {"ag_cards": "t-pine"}


def test_the_down_path_refuses_with_a_count_while_two_tenants_hold_one_slug(scratch: URL) -> None:
    migrate(scratch, "upgrade", HEAD)
    asyncio.run(
        sql(
            scratch,
            insert(
                "registry_agents",
                tenant_id="t-harbor",
                id="ag_a",
                slug="intake",
                team_id="team_a",
                version=1,
                paused=False,
                created_at=AT,
                updated_at=AT,
            ),
            insert(
                "registry_agents",
                tenant_id="t-pine",
                id="ag_b",
                slug="intake",
                team_id="team_b",
                version=1,
                paused=False,
                created_at=AT,
                updated_at=AT,
            ),
        )
    )
    done = alembic(scratch, "downgrade", BEFORE)
    assert done.returncode != 0
    assert "held by more than one tenant, so the install-wide keys would fail: 1 agent slugs" in done.stderr
    asyncio.run(sql(scratch, ("DELETE FROM registry_agents WHERE id = 'ag_b'", {})))
    migrate(scratch, "downgrade", BEFORE)
