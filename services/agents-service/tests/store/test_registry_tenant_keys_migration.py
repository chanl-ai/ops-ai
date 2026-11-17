"""Migration 0108 puts the tenant in the workflow, widget, deployment and channel keys, by failure mode, on a scratch
database at 0107: a tenant whose thread runs a seeded `local` workflow is left without its own copy (so its pinned
digest would not resolve once the policies hold), a tenant with no reference gets one anyway, a second run copies
twice; a version written under a parent of another tenant keeps the wrong tenant and fails the composite key; the down
path leaves the copies behind, or restores install-wide keys while two tenants hold one id."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.tenancy import tenant_scope
from ops_store.testing import DATABASES

from .test_registry_tenant_migration import AT, default, insert, migrate
from .test_registry_tenant_preflight import alembic, scratch_at, sql, thread

BEFORE = "0107_system_reads_agent_pointers"
HEAD = "0108_registry_tenant_keys"


@pytest.fixture(params=DATABASES)
def scratch(request: pytest.FixtureRequest) -> Iterator[URL]:
    url, drop = scratch_at(BEFORE, request.param)
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
    # Down past 0104, which drops thread_budgets' tenant (no default left on SQL Server), and back up.
    migrate(scratch, "downgrade", "0103_eval_cases_runs")
    migrate(scratch, "upgrade", "head")


def _copy_id(tenant: str, source: str) -> str:
    return "ag_" + hashlib.md5(f"{tenant}/{source}".encode()).hexdigest()[:24]


def _agent(tenant: str, agent_id: str, slug: str, team: str, by: str = "seed") -> list[sa.Insert]:
    spec = '{"name": "Intake", "skillPins": [{"skillId": "sk_forms", "version": 2}]}'
    return [
        insert(
            "registry_agents",
            tenant_id=tenant,
            id=agent_id,
            slug=slug,
            team_id=team,
            version=1,
            published_version=1,
            paused=False,
            created_at=AT,
            updated_at=AT,
        ),
        insert(
            "registry_agent_versions",
            tenant_id=tenant,
            agent_id=agent_id,
            version=1,
            spec=spec,
            digest=f"d-{agent_id}",
            note="",
            changes="[]",
            saved_at=AT,
            saved_by=by,
            published_at=AT,
            published_by=by,
        ),
    ]


def _embed(tenant: str, team: str, agent_id: str) -> sa.Insert:
    return insert(
        "widget_deployments",
        id=f"wdp_{tenant}",
        tenant_id=tenant,
        team_id=team,
        name="Help",
        agent_id=agent_id,
        origins='["https://help.harborpine.example"]',
        paused=False,
        created_by="maya@x.example",
        created_at=AT,
        updated_at=AT,
    )


GRAPHS = ("graph_threads", "tenant_id", "team_id", "graph")


def test_a_tenant_on_a_seeded_agent_gets_its_own_copy_that_its_threads_default_and_embed_resolve(scratch: URL) -> None:
    """t-pine's one team chats with, defaults to and embeds the seed agent, and already holds its slug; t-harbor's two
    teams chat with it. Each gets a copy under an id of its own (agents keep the install-wide key `id`), owned by the
    one team that uses it, else the seed's team, with the published version served and the skill pins filled; `local`
    keeps its seed and its own thread. A run stopped after the copies were made copies nothing twice."""
    pine, harbor = _copy_id("t-pine", "ag_seed"), _copy_id("t-harbor", "ag_seed")
    asyncio.run(
        sql(
            scratch,
            *_agent("local", "ag_seed", "intake", "team_ops"),
            *_agent("t-pine", "ag_pine", "intake", "team_cards", by="maya@x.example"),
            thread("local", "team_ops", "agent:ag_seed"),
            thread("t-pine", "team_cards", "agent:ag_seed"),
            default("t-pine", "team_cards", "ag_seed"),
            _embed("t-pine", "team_cards", "ag_seed"),
            thread("t-harbor", "team_claims", "agent:ag_seed"),
            thread("t-harbor", "team_wires", "agent:ag_seed"),
        )
    )
    migrate(scratch, "upgrade", HEAD)
    alembic(scratch, "stamp", BEFORE)
    migrate(scratch, "upgrade", "head")
    assert _rows(scratch, "registry_agents", "tenant_id", "id", "slug", "team_id", "published_version") == sorted(
        [
            ("local", "ag_seed", "intake", "team_ops", "1"),
            ("t-pine", "ag_pine", "intake", "team_cards", "1"),
            ("t-pine", pine, f"intake-{pine[3:9]}", "team_cards", "1"),
            ("t-harbor", harbor, "intake", "team_ops", "1"),
        ]
    )
    assert _rows(scratch, "registry_agent_versions", "tenant_id", "agent_id", "version", "review_id") == sorted(
        [
            ("local", "ag_seed", "1", "None"),
            ("t-pine", "ag_pine", "1", "None"),
            ("t-pine", pine, "1", "copied"),
            ("t-harbor", harbor, "1", "copied"),
        ]
    )
    assert _rows(scratch, *GRAPHS) == sorted(
        [
            ("local", "team_ops", "agent:ag_seed"),
            ("t-pine", "team_cards", f"agent:{pine}"),
            ("t-harbor", "team_claims", f"agent:{harbor}"),
            ("t-harbor", "team_wires", f"agent:{harbor}"),
        ]
    )
    assert _rows(scratch, "team_default_agents", "tenant_id", "agent_id") == [("t-pine", pine)]
    assert _rows(scratch, "widget_deployments", "tenant_id", "agent_id") == [("t-pine", pine)]
    assert ("t-pine", pine, "sk_forms", "2") in _rows(
        scratch, "agent_skill_pins", "tenant_id", "agent_id", "skill_id", "version"
    )

    async def served() -> tuple[dict[str, str], list[tuple[str, str, int | None, bool]]]:
        engine = create_async_engine(scratch)
        try:
            registry = AgentRegistry(engine)
            with tenant_scope("t-pine"):
                owners = await registry.tenant_owners({pine, "ag_seed"})
            return owners, await registry.published_pointers()
        finally:
            await engine.dispose()

    owners, pointers = asyncio.run(served())
    # B's thread, default and embed resolve its copy in its tenant; the restart serves the seed and every copy.
    assert owners == {pine: "team_cards"}
    assert {("local", "ag_seed", 1, False), ("t-pine", pine, 1, False), ("t-harbor", harbor, 1, False)} <= set(pointers)


def test_the_down_path_points_a_tenant_back_at_the_seed_and_keeps_a_copy_it_has_saved_to(scratch: URL) -> None:
    pine, harbor = _copy_id("t-pine", "ag_seed"), _copy_id("t-harbor", "ag_seed")
    asyncio.run(
        sql(
            scratch,
            *_agent("local", "ag_seed", "intake", "team_ops"),
            thread("t-pine", "team_cards", "agent:ag_seed"),
            default("t-pine", "team_cards", "ag_seed"),
            thread("t-harbor", "team_claims", "agent:ag_seed"),
        )
    )
    migrate(scratch, "upgrade", "head")
    edited = _agent("t-harbor", harbor, "intake", "team_claims", by="maya@x.example")[1].values(version=2)
    asyncio.run(sql(scratch, edited))
    migrate(scratch, "downgrade", BEFORE)
    assert _rows(scratch, "registry_agents", "tenant_id", "id") == sorted([("local", "ag_seed"), ("t-harbor", harbor)])
    assert _rows(scratch, "registry_agent_versions", "tenant_id", "agent_id", "version") == sorted(
        [("local", "ag_seed", "1"), ("t-harbor", harbor, "1"), ("t-harbor", harbor, "2")]
    )
    assert _rows(scratch, "graph_threads", "tenant_id", "graph") == sorted(
        [("t-pine", "agent:ag_seed"), ("t-harbor", f"agent:{harbor}")]
    )
    assert _rows(scratch, "team_default_agents", "tenant_id", "agent_id") == [("t-pine", "ag_seed")]
    assert pine not in {r[0] for r in _rows(scratch, "registry_agents", "id")}
