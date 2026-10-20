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
        "secret_audit",
        "send_checks",
        "send_policies",
        "service_outbox",
        "tool_modules",
        "tool_secrets",
    },
    "c-415": {
        "file_blobs",
        "file_idempotency",
        "file_legal_holds",
        "file_read_requests",
        "file_references",
        "file_versions",
        "files",
        "files_outbox",
        "storage_credentials",
        "storage_settings",
        "storage_settings_audit",
        "document_type_examples",
        "document_type_samples",
        "document_type_tests",
        "document_type_versions",
        "document_types",
        "documents_layouts",
        "documents_outbox",
        "extraction_corrections",
        "extractions",
    },
    "c-416": {
        "kb_base_sources",
        "kb_bases",
        "kb_changes",
        "kb_chunks",
        "kb_item_versions",
        "kb_items",
        "kb_retired_bases",
        "kb_runs",
        "kb_sources",
        "model_aliases",
        "model_call_log",
        "model_key_tenants",
        "model_keys",
        "provider_connections",
    },
}


def _tables() -> dict[str, sa.Table]:
    return {t.name: t for chain in chains() for m in chain_metadata(chain) for t in m.tables.values()}


def test_every_table_is_marked_or_waits_for_the_card_that_marks_it() -> None:
    unmarked = {name for name, t in _tables().items() if isolation_kind(t) is None}
    waiting = set().union(*WAITING.values())
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
