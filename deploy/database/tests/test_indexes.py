"""Every foreign key column, and every column a list filters or sorts on (`info=LISTED`, `ops_store.listing`), has an
index that leads with it: an unindexed one is a full scan that grows with the table, on every list and every delete
of the row it points at. An index leads with a column when the column comes first, or after only the tenant and team
columns every statement already names. A primary key or unique constraint counts. A column with none fails here by
name, unless it is on the waiting list of its chain; that list only shrinks, and a listed column that now has an
index fails too, so the entry comes off in the commit that adds the index. No server is needed."""

from __future__ import annotations

import sys
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import chain_metadata, chains

from ops_store.listing import LISTED, LISTED_KEY

# The columns every statement names before any other, so an index may put them first.
SCOPE = {"tenant_id", "team_id"}
# Chain -> foreign key columns with no index yet.
WAITING: dict[str, set[str]] = {
    "kb": {
        "kb_base_sources.source_id",
        "kb_chunks.item_id",
    },
    "models": {
        "model_aliases.provider_id",
    },
    "platform": {
        "api_keys.created_by",
        "members.user_id",
        "password_resets.user_id",
        "role_assignments.role_id",
        "signin_domains.provider_id",
        "signin_flows.provider_id",
        "signin_grants.provider_id",
        "signin_grants.rule_id",
        "signin_group_rules.team_id",
        "signin_identities.user_id",
        "signin_providers.jit_team_id",
        "signin_providers.tenant_id",
    },
    "tools": {
        "connect_links.connection_id",
        "module_egress_hosts.host",
    },
}


def leads(table: sa.Table, column: str) -> bool:
    keys = (c for c in table.constraints if isinstance(c, sa.PrimaryKeyConstraint | sa.UniqueConstraint))
    for group in ([c.name for c in found.columns] for found in (*table.indexes, *keys)):
        if column in group and all(name in SCOPE for name in group[: group.index(column)]):
            return True
    return False


def unindexed(table: sa.Table) -> set[str]:
    needs = [c for c in table.columns if c.foreign_keys or c.info.get(LISTED_KEY)]
    return {f"{table.name}.{c.name}" for c in needs if not leads(table, c.name)}


def _found() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for chain in chains():
        columns: set[str] = set[str]().union(*(unindexed(t) for m in chain_metadata(chain) for t in m.tables.values()))
        if columns:
            out[chain] = columns
    return out


def test_every_foreign_key_and_listed_column_has_an_index_or_waits_for_one() -> None:
    found = _found()
    new = {chain: sorted(cols - WAITING.get(chain, set())) for chain, cols in found.items()}
    assert {c: cols for c, cols in new.items() if cols} == {}, "add an index that leads with each column"
    done = {chain: sorted(cols - found.get(chain, set())) for chain, cols in WAITING.items()}
    assert {c: cols for c, cols in done.items() if cols} == {}, "indexed now: take each off WAITING"


def test_the_scan_names_an_unindexed_foreign_key_and_listed_column_and_passes_an_indexed_one() -> None:
    meta = sa.MetaData()
    sa.Table("parents", meta, sa.Column("id", sa.String(32), primary_key=True))
    child = sa.Table(
        "children",
        meta,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("parent_id", sa.String(32), sa.ForeignKey("parents.id")),
        sa.Column("other_id", sa.String(32), sa.ForeignKey("parents.id")),
        sa.Column("status", sa.String(16), info=LISTED),
        sa.Column("kind", sa.String(16), info=LISTED),
        sa.Column("note", sa.String(16)),
        # After the tenant alone counts; after another column does not.
        sa.Index("ix_children_parent", "tenant_id", "parent_id"),
        sa.Index("ix_children_note_status", "note", "status"),
        sa.Index("ix_children_kind", "kind"),
    )
    assert unindexed(child) == {"children.other_id", "children.status"}


def test_the_waiting_list_only_falls_in_the_history() -> None:
    """An entry added to WAITING in a commit with no `Standards-exception:` trailer: the list and the schema change
    together, so the working tree alone cannot show it."""
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "scripts"))
    import baseline_history  # noqa: PLC0415

    problems = baseline_history.problems(
        root,
        "583fbae33c53c028d7a20873eeb72db811888084",
        ["deploy/database/tests/test_indexes.py"],
        baseline_history.waiting_dict("WAITING"),
    )
    assert problems == []
