"""Every table of every chain says how the database isolates it: tenant-scoped (by tenant, or by tenant and
team when it is also team-owned) or `system(reason)`. A table with neither fails here by name, unless it is on the
waiting list of the card that marks it; that list only shrinks, and a listed table that is now marked fails too, so the
entry comes off in the commit that marks it. No server is needed."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import chain_metadata, chains

from ops_store.schema import isolation_ddl, isolation_kind

# Area -> tables the database does not isolate yet.
WAITING: dict[str, set[str]] = {
    "agents runtime": {
        "channel_cursors",
        "channel_messages",
        "deployments",
        "graph_versions",
        "thread_inbox",
    },
    "agents registry": {
        "registry_agent_versions",
        "registry_agents",
        "registry_guardrail_versions",
        "registry_guardrails",
        "registry_skill_versions",
        "registry_skills",
        "registry_validations",
        "registry_widget_versions",
        "registry_widgets",
        "registry_workflow_versions",
        "registry_workflows",
    },
    "tools": {
        # A module with no team is read and called by every team, and the generated team policy reads only the
        # acting team's rows; it waits for a marking whose policy also reads the tenant's no-team rows.
        "tool_modules",
    },
}


def _tables() -> dict[str, sa.Table]:
    return {t.name: t for chain in chains() for m in chain_metadata(chain) for t in m.tables.values()}


def test_every_table_is_marked_or_waits_for_the_card_that_marks_it() -> None:
    unmarked = {name for name, t in _tables().items() if isolation_kind(t) is None}
    waiting: set[str] = set[str]().union(*WAITING.values())
    assert sorted(unmarked - waiting) == [], "mark these TENANT_SCOPED or system(reason)"
    assert sorted(waiting - unmarked) == [], "now marked: take these off WAITING"


@pytest.mark.parametrize("dialect", ["postgresql", "mssql"])
def test_every_marked_table_compiles_to_its_policy(dialect: str) -> None:
    """A marking the generator cannot meet (a team-owned table without its team column, a tenant table without a
    tenant column) fails here rather than in a migration."""
    for t in _tables().values():
        kind = isolation_kind(t)
        statements = isolation_ddl(t, dialect, chain="probe")
        assert bool(statements) == (kind in ("team", "tenant")), t


# A table holding sign-in material: a sealed value (`*_ct`, `ciphertext`) or a person's own row (`person_id`).
# Each is isolated by the database, or waits here for the card that isolates it; the list only shrinks.
# Every table holding sign-in material is isolated by the database; a new one waits here with its card.
SIGN_IN_MATERIAL_WAITING: set[str] = set()


def _holds_sign_in_material(t: sa.Table) -> bool:
    return any(c.name.endswith("_ct") or c.name in ("ciphertext", "person_id") for c in t.columns)


def test_every_table_holding_sign_in_material_is_isolated_by_the_database() -> None:
    holding = {name for name, t in _tables().items() if _holds_sign_in_material(t)}
    open_ = {name for name in holding if isolation_kind(_tables()[name]) not in ("team", "tenant")}
    assert sorted(open_ - SIGN_IN_MATERIAL_WAITING) == [], "isolate these by tenant and team in the database"
    assert sorted(SIGN_IN_MATERIAL_WAITING - open_) == [], "now isolated or gone: take these off the waiting list"


# A system(...) table names no tenant to the database, so a row in it that carries a tenant or a team is that tenant's
# data with no policy over it. The few that must stay install-wide are listed with the reason.
TENANT_COLUMNS_IN_SYSTEM_TABLES: dict[str, str] = {
    "service_outbox": "tools-service's outbox: the relay reads every tenant's events to deliver them",
    "platform_outbox": "platform-service's outbox: the relay delivers events across tenants",
    "oauth_clients": "a registered OAuth client has no tenant until a person allows it",
}


def test_a_system_table_with_a_tenant_or_team_column_is_listed_with_its_reason() -> None:
    carrying = {
        name
        for name, t in _tables().items()
        if isolation_kind(t) == "system" and {"tenant_id", "tenant", "team_id", "team"} & set(t.columns.keys())
    }
    assert sorted(carrying - TENANT_COLUMNS_IN_SYSTEM_TABLES.keys()) == [], "police these by tenant or list them"
    assert sorted(TENANT_COLUMNS_IN_SYSTEM_TABLES.keys() - carrying) == [], "no longer carry a tenant: unlist them"
