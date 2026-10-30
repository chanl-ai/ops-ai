"""Every table of every chain says how the database isolates it (c-410): tenant-scoped (by tenant, or by tenant and
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

# Card -> tables the database does not isolate yet, by the c-408 design's build cards.
WAITING: dict[str, set[str]] = {
    "c-411": {"signin_email_failures"},
    "c-412": {
        "channel_cursors",
        "channel_files",
        "channel_messages",
        "deployments",
        "graph_versions",
        "model_call_records",
        "thread_budgets",
        "thread_inbox",
        "thread_leases",
        "timers",
    },
    "c-413": {
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
    "c-414": {
        # connect_links (c-558) is team-owned and read through team_visible; its database policy comes with these.
        "connect_links",
        "connection_audit",
        "connection_environments",
        "connection_tokens",
        "connections",
        "egress_audit",
        "egress_hosts",
        "egress_ranges",
        "gateway_calls",
        "gateway_fences",
        "module_approvals",
        "module_egress_hosts",
        "module_operations",
        "module_versions",
        "oauth_states",
        "operation_mocks",
        "operation_rate_windows",
        "plugin_bindings",
        # Account-scoped by design, with no team: the platform's own OAuth app secret per plugin (c-565).
        "plugin_app_keys",
        "secret_audit",
        "send_checks",
        "send_policies",
        "tool_modules",
        "tool_secrets",
    },
    # provider_keys (c-509) is filtered by tenant in its store; the database policy comes with the other model tables.
    "c-416": {
        "model_aliases",
        "model_call_log",
        "model_key_tenants",
        "model_keys",
        "provider_connections",
        "provider_keys",
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
