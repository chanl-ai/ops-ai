"""kb-service's tables, on the shared database under their own migration chain (alembic_version_kb).

A knowledge base belongs to a department team and names its owner; a source brings documents in (file sources only
in this slice, holding file ids, never bytes); a knowledge base reads the sources attached to it. Every row carries
its tenant and its team, and the database holds each transaction to them (kb_0011): every transaction is
`Store.tx()` as `ops_kb_tenant`, and a link, document, version, chunk, change and run take the
team of the base, source or document they belong to.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal, NamedTuple, TypedDict, cast

import sqlalchemy as sa
from pydantic import BeforeValidator, JsonValue
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict
from ops_service_kit.http import Out
from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.audit import AUDIT_EVENT, AUDIT_ROUTE
from ops_store.audit import record as record_audit
from ops_store.database import open_database, reachable
from ops_store.dialect import Vector, db_after, db_now, insert_ignore, locked
from ops_store.listing import LISTED, ListPage, list_page
from ops_store.outbox import Event, KbChanged, Poster, Relay, outbox_table, relay
from ops_store.outbox import add as add_event
from ops_store.rows import one, rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, dialect_indexes, postgres_only
from ops_store.search import contains
from ops_store.store import Store
from ops_store.team_scope import any_team, team_visible

__all__ = [
    "ROLE",
    "SYSTEM_ROLE",
    "AsyncEngine",
    "KnowledgeStore",
    "engine_for",
    "kb_outbox",
    "metadata",
    "outbox_relay",
    "reachable",
]

metadata = sa.MetaData()

# The role every kb transaction runs as, which the team policy applies to, and the start-up move's role that reads which
# tenants hold a source (kb_0011).
ROLE = "ops_kb_tenant"
SYSTEM_ROLE = "ops_kb_system"
# The start-up move between file stores reads every tenant's sources before it knows a tenant.
MOVE_TENANTS = "background process: the start-up move between file stores lists the tenants holding a source"

kb_bases = sa.Table(
    "kb_bases",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("slug", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("color", sa.String(32), nullable=False),
    # Who answers for what the knowledge base serves; required, so a cited answer always has someone to ask.
    sa.Column("owner", sa.String(200), nullable=False),
    sa.Column("collections", sa.JSON, nullable=False),
    sa.Column("retrieval", sa.JSON, nullable=False),
    # Its answer, sync, access and source-default settings (service.settings_of); null: the defaults (kb_0024).
    sa.Column("settings", sa.JSON),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_refreshed_at", sa.DateTime(timezone=True)),
    # The template the provisioning service made it from, and how the platform protects it: `system` cannot be
    # changed by a person, `managed` can, and the template's fields come back on the next provisioning run.
    sa.Column("template_id", sa.String(120), info=LISTED),
    sa.Column("protection", sa.String(16)),
    # The base's own documents source, which Add documents adds files to; found by id, so renaming the base or
    # the source never makes a second one. Null until the first Add documents.
    sa.Column("documents_source_id", sa.String(64)),
    # Rises with each rename or recolour and once more on delete; `kb.changed` carries it (kb_0025).
    sa.Column("revision", sa.Integer, nullable=False, server_default=sa.text("0")),
    # Name uniqueness per team: two of a team's knowledge bases with one name make a grant ambiguous to the person
    # granting it. Another team's names are not seen.
    sa.UniqueConstraint("tenant_id", "team_id", "name", name="uq_kb_bases_name"),
    # The list's `templateId` filter (kb_0028).
    sa.Index("ix_kb_bases_template", "tenant_id", "template_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_sources = sa.Table(
    "kb_sources",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("type", sa.String(32), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("collection", sa.String(120), nullable=False),
    sa.Column("owner", sa.String(200), nullable=False),
    sa.Column("sensitivity", sa.String(16), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("tags", sa.JSON, nullable=False),
    # File ids in files-service; the source never holds bytes.
    sa.Column("file_ids", sa.JSON, nullable=False),
    # The name each file was uploaded under here, by file id: a deduplicated blob keeps its first uploader's name.
    # Set by the application: MySQL 8 refuses a literal default on a JSON column (kb_0005).
    sa.Column("file_names", sa.JSON, nullable=True, default=dict),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_sync_at", sa.DateTime(timezone=True)),
    sa.Column("last_run_status", sa.String(16)),
    # A "tool" source's reading: plugin, source, its two tools, the connection, the schedule, the watermark and
    # saved cursor of the last sync, and why it is paused; null for a file source.
    sa.Column("config", sa.JSON),
    # Held by the sync running now, so the schedule never starts a second one on the same source.
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    # Who holds the lease (a token per sync or rebuild): only its holder renews or releases it.
    sa.Column("lease_owner", sa.String(64)),
    # Reading, cleaning, splitting, rules and metadata (source_settings.py); null: the kind's defaults.
    sa.Column("settings", sa.JSON),
    # Its health: when a sync last indexed or kept its items, since when its syncs have failed, and how many in a row.
    sa.Column("last_good_sync_at", sa.DateTime(timezone=True)),
    sa.Column("failing_since", sa.DateTime(timezone=True)),
    sa.Column("failures_in_row", sa.Integer, nullable=False, server_default="0"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_base_sources = sa.Table(
    "kb_base_sources",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("kb_id", sa.String(64), primary_key=True),
    sa.Column("source_id", sa.String(64), primary_key=True),
    sa.ForeignKeyConstraint(
        ["tenant_id", "kb_id"], ["kb_bases.tenant_id", "kb_bases.id"], ondelete="CASCADE", name="fk_kb_link_base"
    ),
    sa.ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["kb_sources.tenant_id", "kb_sources.id"],
        ondelete="CASCADE",
        name="fk_kb_link_source",
    ),
    # A source's bases, and the cascade when a source is deleted, without reading every link of the tenant.
    sa.Index("ix_kb_base_sources_source", "tenant_id", "source_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# A deleted base's id, so a search naming it skips it rather than refusing (agents keep citing their other bases).
kb_retired_bases = sa.Table(
    "kb_retired_bases",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("retired_by", sa.String(200), nullable=False),
    sa.Column("retired_at", sa.DateTime(timezone=True), nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_items = sa.Table(
    "kb_items",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("source_id", sa.String(64), nullable=False),
    # One document per name in a source: a file uploaded again under the same name is its next version.
    sa.Column("path", sa.String(400), nullable=False),
    sa.Column("title", sa.String(400), nullable=False),
    sa.Column("mime", sa.String(120), nullable=False),
    sa.Column("size", sa.Integer, nullable=False),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # pending | reading | indexed | failed
    sa.Column("error_class", sa.String(32)),
    sa.Column("error", sa.Text),
    # Indexed, with pages left unread (no text layer, or past the page limit), and why.
    sa.Column("warning", sa.Text),
    sa.Column("page_count", sa.Integer),
    sa.Column("chunk_count", sa.Integer, nullable=False),
    sa.Column("owner", sa.String(200), nullable=False),
    # A person confirmed the document is right; who and when, so the claim can be checked.
    sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("verified_by", sa.String(200)),
    sa.Column("verified_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("processed_at", sa.DateTime(timezone=True)),
    # Read through a connection's tools: the system's change marker, the item this one is attached to, and its
    # address in the system for a citation.
    sa.Column("marker", sa.String(120)),
    sa.Column("parent_id", sa.String(64)),
    sa.Column("url", sa.Text),
    # How a file source's item was read: the reader version and its OCR settings (reading-1:auto:eng), so a change
    # to either asks for a new reading while a chunk-settings change splits the stored one again.
    sa.Column("read_with", sa.String(120)),
    # The digest of the cleaning, splitting and metadata settings its pieces were built under (index_key).
    sa.Column("indexed_with", sa.String(32)),
    # The digest of its text after cleaning, and the newer item in a base it reads into that holds the same text:
    # search leaves an item out while it names one.
    sa.Column("content_digest", sa.String(80)),
    sa.Column("duplicate_of", sa.String(64)),
    # Where a fetched item sits at its source (a library folder, a space's page tree), and the fields the source gives
    # it, which the source's metadata mapping reads (`field:<name>`).
    sa.Column("folder", sa.String(400)),
    sa.Column("fields", sa.JSON),
    # The version tag its last fetch gave (ETag, md5, revision), sent back so the system answers `unchanged`.
    sa.Column("tag", sa.String(200)),
    # A short digest of each paragraph of its cleaned text, which a website source counts across its pages.
    sa.Column("lines", sa.JSON),
    # Syncs in a row the item answered gone (404 or 410) at its source; at two it is removed and tombstoned.
    sa.Column("gone_count", sa.Integer, nullable=False, server_default="0"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["kb_sources.tenant_id", "kb_sources.id"],
        ondelete="CASCADE",
        name="fk_kb_item_source",
    ),
    sa.UniqueConstraint("tenant_id", "source_id", "path", name="uq_kb_items_path"),
    sa.Index("ix_kb_items_content", "tenant_id", "content_digest"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_item_versions = sa.Table(
    "kb_item_versions",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("item_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # current | superseded
    # The user and group ids the source system lets see this version; stored, enforced once per-item access ships.
    sa.Column("allowed", sa.JSON),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "item_id"], ["kb_items.tenant_id", "kb_items.id"], ondelete="CASCADE", name="fk_kb_version_item"
    ),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

kb_chunks = sa.Table(
    "kb_chunks",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("item_id", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("title", sa.String(400), nullable=False),
    sa.Column("section", sa.String(400), nullable=False),
    sa.Column("page", sa.Integer),
    sa.Column("tokens", sa.Integer, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    # Set when a newer version replaces the item: a withdrawn chunk is never returned, so no answer cites two versions.
    sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
    # The values the source's metadata mapping gives the piece (department, owner, product, ...).
    sa.Column("metadata", sa.JSON),
    sa.ForeignKeyConstraint(
        ["tenant_id", "item_id"], ["kb_items.tenant_id", "kb_items.id"], ondelete="CASCADE", name="fk_kb_chunk_item"
    ),
    # An item's pieces (its detail, a re-index, the cascade when it is deleted) without reading every piece.
    sa.Index("ix_kb_chunks_item", "tenant_id", "item_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

# What search matches, apart from what it cites: each piece's own text with its context header, its smaller children
# under parent and child, and the questions written for it. A match on any unit returns its piece (`chunk_id`), once.
kb_units = sa.Table(
    "kb_units",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("chunk_id", sa.String(64), nullable=False),
    sa.Column("item_id", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),  # self | child | question | faq
    sa.Column("position", sa.Integer, nullable=False),
    # The document title and section path, which weigh above the unit's own text.
    sa.Column("heading", sa.String(800), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column(
        "tsv",
        TSVECTOR,
        sa.Computed(
            "setweight(to_tsvector('english', coalesce(heading, '')), 'A')"
            " || setweight(to_tsvector('english', text), 'B')",
            persisted=True,
        ),
    ),
    sa.ForeignKeyConstraint(
        ["tenant_id", "chunk_id"], ["kb_chunks.tenant_id", "kb_chunks.id"], ondelete="CASCADE", name="fk_kb_unit_chunk"
    ),
    sa.Index("ix_kb_units_chunk", "tenant_id", "chunk_id"),
    # Its GIN index on tsv is the migration's (kb_0016): PostgreSQL's form only, as search runs there.
    info={**TENANT_SCOPED, **TEAM_OWNED, **dialect_indexes("ix_kb_units_tsv")},
)


# Each index unit's embedding, with the model and width it was made with (kb_0021, only where pgvector is installed).
kb_unit_vectors = sa.Table(
    "kb_unit_vectors",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("unit_id", sa.String(64), primary_key=True),
    sa.Column("chunk_id", sa.String(64), nullable=False),
    sa.Column("item_id", sa.String(64), nullable=False),
    sa.Column("model", sa.String(120), nullable=False),
    sa.Column("width", sa.Integer, nullable=False),
    sa.Column("embedding", Vector(), nullable=False),
    sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "unit_id"], ["kb_units.tenant_id", "kb_units.id"], ondelete="CASCADE", name="fk_kb_vector_unit"
    ),
    sa.Index("ix_kb_unit_vectors_chunk", "tenant_id", "chunk_id"),
    # The HNSW index for the environment's width is made by kb_0021 through ops_store.dialect.
    info={**TENANT_SCOPED, **TEAM_OWNED, **postgres_only(), **dialect_indexes("ix_kb_unit_vectors_hnsw_")},
)


kb_changes = sa.Table(
    "kb_changes",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("item_id", sa.String(64), nullable=False),
    sa.Column("source_id", sa.String(64), nullable=False),
    sa.Column("title", sa.String(400), nullable=False),
    sa.Column("section", sa.String(400), nullable=False),
    sa.Column("from_version", sa.Integer, nullable=False),
    sa.Column("to_version", sa.Integer, nullable=False),
    sa.Column("before", sa.Text, nullable=False),
    sa.Column("after", sa.Text, nullable=False),
    sa.Column("changed_by", sa.String(200), nullable=False),
    sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    # sync: a version a sync applied; faq: a drafted question-and-answer pair waiting for, or past, review.
    sa.Column("origin", sa.String(16), nullable=False, server_default="sync"),
    # applied (a sync's); pending, approved, rejected, superseded or source_changed (a draft's).
    sa.Column("status", sa.String(16), nullable=False, server_default="applied"),
    # A draft's question, answer and quote, its section path and digest, and where the quote sits in its piece.
    sa.Column("detail", sa.JSON),
    sa.Column("decided_by", sa.String(200)),
    sa.Column("decided_at", sa.DateTime(timezone=True)),
    # No foreign key to the item: the record of who changed what outlives the document's removal.
    sa.Index("ix_kb_changes_at", "tenant_id", "changed_at"),
    sa.Index("ix_kb_changes_item_origin", "tenant_id", "item_id", "origin"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# A change row as it leaves the store: every column but the tenant and team, which the caller already holds.
CHANGE = tuple(col for col in kb_changes.c if col.name not in ("tenant_id", "team_id"))

kb_runs = sa.Table(
    "kb_runs",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("source_id", sa.String(64), nullable=False),
    sa.Column("trigger", sa.String(16), nullable=False),  # manual | full | retry
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("duration_sec", sa.Float(), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("counts", sa.JSON, nullable=False),
    sa.Column("errors", sa.JSON, nullable=False),
    sa.Column("log", sa.JSON, nullable=False),
    sa.Column("started_by", sa.String(200), nullable=False),
    # A run in the background is written when it starts (status running) and again when it ends.
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    # Who asked a running rebuild to stop; it stops between two items.
    sa.Column("cancelled_by", sa.String(200)),
    sa.ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["kb_sources.tenant_id", "kb_sources.id"],
        ondelete="CASCADE",
        name="fk_kb_run_source",
    ),
    sa.Index("ix_kb_runs_source", "tenant_id", "source_id", "started_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# The audit entries of settings changes, written in the transaction of the change and relayed to platform-service's
# one audit log (ops_store.audit); read across tenants by the relay as ops_kb_system.
kb_outbox = outbox_table(metadata, "kb_outbox", info=TENANT_SCOPED)

# Where kb_outbox's events go: an audit entry to platform-service's account audit log (`audit:create`), its team in the
# token alone; every other event (a source that keeps failing, a knowledge base changed) to agents-service's
# /v1/events (`events:emit`), where the workflows that listen to it run.
RELAY_ROUTES = {AUDIT_EVENT: ("platform",), "*": ("agents",)}


def outbox_relay(engine: AsyncEngine, targets: Mapping[str, Poster]) -> Relay:
    """kb_outbox's relay to the services in `targets` ("platform", "agents"); one this installation does not run is
    left out, and its events are delivered by doing nothing."""
    return relay(
        engine,
        kb_outbox,
        routes=RELAY_ROUTES,
        targets=targets,
        role=SYSTEM_ROLE,
        team_in_token=frozenset({"platform"}),
        path_by_target={"platform": AUDIT_ROUTE},
    )


class UnitWrite(TypedDict):
    """One way a new piece is searched (its own text, a child, a question), as `pieces` builds it."""

    tenant_id: str
    id: str
    chunk_id: str
    item_id: str
    kind: str
    position: int
    heading: str
    text: str


class UnitStored(UnitWrite):
    team_id: str


class PieceFields(TypedDict):
    tenant_id: str
    id: str
    item_id: str
    version: int
    position: int
    title: str
    section: str
    page: int | None
    tokens: int
    text: str
    metadata: dict[str, str] | None


class PieceWrite(PieceFields):
    """A new piece of an item with the units it is searched as, as `pieces` builds it."""

    units: list[UnitWrite]


class PieceStored(PieceFields):
    """A piece as kb_chunks holds it, in the team it is written in."""

    team_id: str


def _with_team(chunks: list[PieceWrite], team: str) -> tuple[list[PieceStored], list[UnitStored]]:
    """Pieces and their index units (each piece's `units`), both in the team they are written in."""
    rows: list[PieceStored] = []
    units: list[UnitStored] = []
    for ch in chunks:
        rows.append(
            PieceStored(
                tenant_id=ch["tenant_id"],
                id=ch["id"],
                item_id=ch["item_id"],
                version=ch["version"],
                position=ch["position"],
                title=ch["title"],
                section=ch["section"],
                page=ch["page"],
                tokens=ch["tokens"],
                text=ch["text"],
                metadata=ch["metadata"],
                team_id=team,
            )
        )
        units += [UnitStored(**u, team_id=team) for u in ch["units"]]
    return rows, units


# What a kept piece takes from the new split: where it sits and the version it now belongs to.
MOVED: tuple[Literal["version", "position", "title", "section", "page", "metadata", "tokens"], ...] = (
    "version",
    "position",
    "title",
    "section",
    "page",
    "metadata",
    "tokens",
)


def _piece_key(text: str, units: list[tuple[str, str]]) -> str:
    """What decides a piece is unchanged: its text and what it is searched as (an approved FAQ unit aside, which
    belongs to the review, not the split)."""
    body = "\x1f".join([" ".join(text.split()), *sorted(f"{k}\x1e{t}" for k, t in units if k != "faq")])
    return hashlib.sha256(body.encode()).hexdigest()


async def _keep_unchanged(
    c: AsyncConnection, tenant: str, item_id: str, chunks: list[PieceStored], units: list[UnitStored]
) -> tuple[list[PieceStored], list[UnitStored]]:
    """Withdraws the item's live pieces a new split does not keep, and keeps those it does: a new piece with the same
    text and units as a live one takes over that row (its id, units and vectors), with its new place and version, so a
    changed page re-embeds only the pieces that changed. Returns the pieces and units still to insert."""
    ch, u = kb_chunks, kb_units
    live = (
        await c.execute(
            sa.select(ch.c.id, ch.c.text).where(
                ch.c.tenant_id == tenant, ch.c.item_id == item_id, ch.c.withdrawn_at.is_(None), team_visible(ch)
            )
        )
    ).all()
    held: dict[str, list[tuple[str, str]]] = {}
    for chunk_id, kind, text in (
        await c.execute(
            sa.select(u.c.chunk_id, u.c.kind, u.c.text).where(
                u.c.tenant_id == tenant, u.c.chunk_id.in_([r[0] for r in live]), team_visible(u)
            )
        )
    ).all():
        held.setdefault(str(chunk_id), []).append((str(kind), str(text)))
    free: dict[str, list[str]] = {}
    for chunk_id, text in live:
        free.setdefault(_piece_key(str(text), held.get(str(chunk_id), [])), []).append(str(chunk_id))
    units_of: dict[str, list[UnitStored]] = {}
    for unit in units:
        units_of.setdefault(str(unit["chunk_id"]), []).append(unit)
    insert: list[PieceStored] = []
    kept: set[str] = set()
    for row in chunks:
        mine = units_of.get(str(row["id"]), [])
        same = free.get(_piece_key(str(row["text"]), [(str(x["kind"]), str(x["text"])) for x in mine]))
        if same:
            old = same.pop()
            kept.add(old)
            moved = {k: row[k] for k in MOVED}
            await c.execute(sa.update(ch).where(ch.c.tenant_id == tenant, ch.c.id == old).values(**moved))
        else:
            insert.append(row)
    await c.execute(
        sa.update(ch)
        .where(ch.c.tenant_id == tenant, ch.c.item_id == item_id, ch.c.withdrawn_at.is_(None), ch.c.id.notin_(kept))
        .values(withdrawn_at=db_now())
    )
    ids = {str(r["id"]) for r in insert}
    return insert, [x for x in units if str(x["chunk_id"]) in ids]


# A draft's statuses that still wait for its knowledge owner; every other status is resolved.
DECIDABLE = ("pending", "source_changed")


class BaseName(Out):
    id: str
    name: str


class BaseOption(Out):
    id: str
    name: str
    description: str
    owner: str


class ChunkRow(Out):
    """A live piece of an item, as its detail and a re-sync's change read it."""

    id: str
    position: int
    section: str
    page: int | None
    tokens: int
    text: str
    metadata: dict[str, JsonValue] | None


class UnitRow(Out):
    """What one piece is searched as: its own text, a child or a likely question."""

    chunk_id: str
    kind: str
    position: int
    text: str


class VersionRow(Out):
    version: int
    digest: str
    status: str
    allowed: list[JsonValue] | None
    created_at: datetime


class ChangeRow(Out):
    """A change in the Changes queue: a version a sync applied or holds for review, or a drafted FAQ pair."""

    id: str
    item_id: str
    source_id: str
    title: str
    section: str
    from_version: int
    to_version: int
    before: str
    after: str
    changed_by: str
    changed_at: datetime
    origin: str
    status: str
    detail: dict[str, JsonValue] | None
    decided_by: str | None
    decided_at: datetime | None


def _whole_counts(value: object) -> object:
    """A run's counts as whole numbers. A row an older build wrote may hold a count as a decimal (2.0), a string
    ("3") or null: a number is kept as its whole part, anything else is left out, so its run list still answers."""
    if not isinstance(value, dict):
        return value
    out: dict[str, int] = {}
    for k, v in cast(dict[object, object], value).items():
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, int | float):
            out[str(k)] = int(v)
        elif isinstance(v, str) and v.strip().lstrip("-").isdigit():
            out[str(k)] = int(v.strip())
    return out


class BaseRow(Out):
    """A knowledge base as stored, but the tenant, which the caller already holds."""

    id: str
    team_id: str
    name: str
    slug: str
    description: str
    color: str
    owner: str
    collections: list[str]
    retrieval: dict[str, JsonValue]
    settings: dict[str, JsonValue] | None
    created_by: str
    created_at: datetime
    last_refreshed_at: datetime | None
    template_id: str | None
    protection: str | None
    documents_source_id: str | None
    revision: int


# Every column of kb_bases but the tenant.
BASE_COLUMNS = [c for c in kb_bases.c if c.name != "tenant_id"]


class SourceRow(Out):
    """A source as stored, but the tenant, with `item_counts` (its documents by status, and `chunks` indexed) and the
    database's clock when it was read (`db_now`), which a lease is judged by."""

    id: str
    team_id: str
    type: str
    name: str
    collection: str
    owner: str
    sensitivity: str
    status: str
    tags: list[str]
    file_ids: list[str]
    file_names: dict[str, str] | None
    created_by: str
    created_at: datetime
    last_sync_at: datetime | None
    last_run_status: str | None
    config: dict[str, JsonValue] | None
    lease_until: datetime | None
    lease_owner: str | None
    settings: dict[str, JsonValue] | None
    last_good_sync_at: datetime | None
    failing_since: datetime | None
    failures_in_row: int
    db_now: datetime
    item_counts: dict[str, int]


# Every column of kb_sources but the tenant.
SOURCE_COLUMNS = [c for c in kb_sources.c if c.name != "tenant_id"]


class RunRow(Out):
    """One sync run of a source: running, or ended with its counts, errors and log."""

    id: str
    source_id: str
    trigger: str
    started_at: datetime
    duration_sec: float
    status: str
    counts: Annotated[dict[str, int], BeforeValidator(_whole_counts)]
    errors: list[JsonValue]
    log: list[JsonValue]
    finished_at: datetime | None = None
    cancelled_by: str | None = None


class ItemRow(Out):
    """A document of a source: its file, current version, reading state and what its fetch and index were built
    from. `team_id` stays: the schedule reads which team's file each waiting item belongs to."""

    team_id: str
    id: str
    source_id: str
    path: str
    title: str
    mime: str
    size: int
    file_id: str
    digest: str
    version: int
    status: str
    error_class: str | None
    error: str | None
    warning: str | None
    page_count: int | None
    chunk_count: int
    owner: str
    verified: bool
    verified_by: str | None
    verified_at: datetime | None
    created_at: datetime
    processed_at: datetime | None
    marker: str | None
    parent_id: str | None
    url: str | None
    read_with: str | None
    indexed_with: str | None
    content_digest: str | None
    duplicate_of: str | None
    folder: str | None
    fields: dict[str, JsonValue] | None
    tag: str | None
    lines: list[JsonValue] | None
    gone_count: int


# Every column of kb_items but the tenant, which the caller already holds.
ITEM_COLUMNS = [c for c in kb_items.c if c.name != "tenant_id"]


class SameText(Out):
    """An indexed document of a base this one shares, holding the same text."""

    id: str
    title: str
    source_id: str
    processed_at: datetime | None


class ChangePage(NamedTuple):
    rows: list[ChangeRow]
    total: int
    views: dict[str, int]
    origins: dict[str, int]


class SourcePage(NamedTuple):
    """A page of sources (`page["data"]` the rows as read), with each row's item counts, the bases each feeds by
    source id, and the ids with a run going."""

    page: ListPage
    sources: list[SourceRow]
    feeds: dict[str, list[BaseName]]
    running: set[str]


async def _item_counts(c: AsyncConnection, tenant: str, ids: list[str] | None) -> dict[str, dict[str, int]]:
    """Each source's documents by status, and `chunks` for its indexed ones, from its items; every source's when
    `ids` is None."""
    i = kb_items.c
    counted = (
        sa.select(i.source_id, i.status, sa.func.count().label("n"), sa.func.coalesce(sa.func.sum(i.chunk_count), 0))
        .where(i.tenant_id == tenant, team_visible(kb_items))
        .group_by(i.source_id, i.status)
    )
    if ids is not None:
        counted = counted.where(i.source_id.in_(ids))
    counts: dict[str, dict[str, int]] = {}
    for source_id, status, n, chunks in await c.execute(counted):
        mine = counts.setdefault(str(source_id), {})
        mine[str(status)] = int(n)
        if status == "indexed":
            mine["chunks"] = int(chunks)
    return counts


def _word(word: str) -> sa.ColumnClause[str]:
    """A fixed word written into the statement, not bound: a GROUP BY must name the same expression the select does,
    and two bound copies of one value are two parameters to the database."""
    return sa.literal_column(f"'{word}'", sa.String())


class BasePage(NamedTuple):
    """A page of knowledge bases (`page["data"]` the rows as read), with the source ids each reads and those
    sources."""

    page: ListPage
    bases: list[BaseRow]
    links: dict[str, list[str]]
    sources: list[SourceRow]


async def _sources_in(c: AsyncConnection, tenant: str, ids: list[str] | None) -> list[SourceRow]:
    """The team's sources, or those of `ids`, each with its item counts."""
    q = sa.select(*SOURCE_COLUMNS, db_now().label("db_now")).where(
        kb_sources.c.tenant_id == tenant, team_visible(kb_sources)
    )
    if ids is not None:
        q = q.where(kb_sources.c.id.in_(ids))
    rows = [dict(r) for r in (await c.execute(q)).mappings()]
    counts = await _item_counts(c, tenant, ids)
    return [SourceRow.model_validate({**r, "item_counts": counts.get(r["id"], {})}) for r in rows]


class KnowledgeStore(Store):
    """kb-service's door to its knowledge bases and sources, always inside one tenant. Creating a knowledge base with
    its links, attaching sources and removing a source with its links each land whole."""

    role = ROLE
    system_role = SYSTEM_ROLE
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    @staticmethod
    async def _team_of(c: AsyncConnection, table: sa.Table, tenant: str, row_id: str) -> str:
        """The team of a base, source or document, which the rows written under it take."""
        q = sa.select(table.c.team_id).where(table.c.tenant_id == tenant, table.c.id == row_id, team_visible(table))
        return str((await c.execute(q)).scalar_one())

    async def bases(self, tenant: str) -> list[BaseRow]:
        async with self.tx() as c:
            q = sa.select(*BASE_COLUMNS).where(kb_bases.c.tenant_id == tenant, team_visible(kb_bases))
            return await rows(c, q, BaseRow)

    async def taken(self, tenant: str, *, name: str | None = None, kb_id: str | None = None) -> list[BaseName]:
        """The caller's team's bases holding `name` (any case) or `kb_id`. A name is unique in a team; an id another
        team holds is refused by the insert (`create_base`), without naming that team."""
        t = kb_bases.c
        wanted = [sa.func.lower(t.name) == name.lower()] if name else []
        wanted += [t.id == kb_id] if kb_id else []
        if not wanted:
            return []
        q = sa.select(t.id, t.name).where(t.tenant_id == tenant, sa.or_(*wanted), team_visible(kb_bases))
        async with self.tx() as c:
            return await rows(c, q, BaseName)

    async def team_bases(self, tenant: str, team: str | None) -> list[BaseRow]:
        """The bases a person in `team` reads: the team's and those no team owns, as the picker offers."""
        t = kb_bases.c
        scope = t.team_id.is_(None) if team is None else sa.or_(t.team_id.is_(None), t.team_id == team)
        async with self.tx() as c:
            q = sa.select(*BASE_COLUMNS).where(t.tenant_id == tenant, scope, team_visible(kb_bases))
            return await rows(c, q, BaseRow)

    async def base_options(
        self, tenant: str, team: str | None, *, search: str, offset: int, limit: int, ids: list[str] | None = None
    ) -> list[BaseOption]:
        """Knowledge bases a picker offers, by name: the caller's team's and those no team owns, whose name contains
        `search`, or exactly `ids` when given. LIMIT and OFFSET run in the query."""
        t = kb_bases.c
        scope = t.team_id.is_(None) if team is None else sa.or_(t.team_id.is_(None), t.team_id == team)
        q = sa.select(t.id, t.name, t.description, t.owner).where(t.tenant_id == tenant, scope, team_visible(kb_bases))
        q = q.where(t.id.in_(ids) if ids is not None else contains(t.name, search))
        q = q.order_by(sa.func.lower(t.name), t.id).offset(offset).limit(limit)
        async with self.tx() as c:
            return await rows(c, q, BaseOption)

    async def base(self, tenant: str, kb_id: str) -> BaseRow | None:
        async with self.tx() as c:
            q = sa.select(*BASE_COLUMNS).where(
                kb_bases.c.tenant_id == tenant, kb_bases.c.id == kb_id, team_visible(kb_bases)
            )
            return await one(c, q, BaseRow)

    async def tenants(self) -> list[str]:
        """Every tenant holding a source; only the start-up move between file stores reads across tenants."""
        async with self.system_tx(MOVE_TENANTS) as c:
            q = sa.select(kb_sources.c.tenant_id).where(any_team(kb_sources, MOVE_TENANTS))
            return [str(r[0]) for r in await c.execute(q.distinct())]

    async def sources(self, tenant: str, ids: list[str] | None = None) -> list[SourceRow]:
        """Each source with `item_counts`, its documents by status (pending, indexed, failed), so what a source says
        about its documents is what its items are."""
        async with self.tx() as c:
            return await _sources_in(c, tenant, ids)

    async def base_page(self, tenant: str, params: ListParams) -> BasePage:
        """One page of the team's knowledge bases, newest first, searched by name, description or owner, filtered by
        `templateId` and counted by health in SQL; then the page's links and the sources they read, so the statements
        are the same number whatever the page size. Health is the row's (`service._base`): never refreshed, else
        degraded while a document of a source it reads failed, else healthy."""
        b, link, item = kb_bases.c, kb_base_sources.c, kb_items.c
        failed = (
            sa.select(link.kb_id)
            .select_from(
                kb_base_sources.join(
                    kb_items, sa.and_(item.tenant_id == link.tenant_id, item.source_id == link.source_id)
                )
            )
            .where(link.tenant_id == tenant, item.status == "failed")
            .where(team_visible(kb_base_sources), team_visible(kb_items))
            .distinct()
            .subquery("failed")
        )
        health = sa.case(
            (b.last_refreshed_at.is_(None), _word("never")),
            # The derived table holds only bases with a failed document: a match is the test, with no value bound.
            (failed.c.kb_id.is_not(None), _word("degraded")),
            else_=_word("healthy"),
        )
        q = (
            sa.select(*BASE_COLUMNS)
            .select_from(kb_bases.outerjoin(failed, failed.c.kb_id == b.id))
            .where(b.tenant_id == tenant, team_visible(kb_bases))
        )
        async with self.tx() as c:
            page = await list_page(
                c,
                q,
                params,
                search=[b.name, b.description, b.owner],
                default_sort=b.created_at.desc(),
                filters={"templateId": b.template_id},
                facets={"health": health},
            )
            found = [BaseRow.model_validate(r) for r in page["data"]]
            if not found:
                return BasePage(page, [], {}, [])
            linked = (
                sa.select(link.kb_id, link.source_id)
                .where(link.tenant_id == tenant, link.kb_id.in_([x.id for x in found]), team_visible(kb_base_sources))
                .order_by(link.kb_id, link.source_id)
            )
            links: dict[str, list[str]] = {}
            for kb_id, source_id in await c.execute(linked):
                links.setdefault(str(kb_id), []).append(str(source_id))
            read = sorted({s for ids in links.values() for s in ids})
            sources = await _sources_in(c, tenant, read) if read else []
        return BasePage(page, found, links, sources)

    async def source_page(self, tenant: str, params: ListParams) -> SourcePage:
        """One page of the team's sources, newest first, searched by name, owner or collection and counted by type
        and status in SQL; then, for the page's sources only, their item counts, the bases each feeds and whether a
        run is going, so the statements are the same number whatever the page size."""
        s = kb_sources.c
        q = sa.select(*SOURCE_COLUMNS, db_now().label("db_now")).where(s.tenant_id == tenant, team_visible(kb_sources))
        async with self.tx() as c:
            page = await list_page(
                c,
                q,
                params,
                search=[s.name, s.owner, s.collection],
                default_sort=s.created_at.desc(),
                facets={"type": s.type, "status": s.status},
            )
            ids = [str(r["id"]) for r in page["data"]]
            if not ids:
                return SourcePage(page, [], {}, set())
            counts = await _item_counts(c, tenant, ids)
            link, base = kb_base_sources.c, kb_bases.c
            fed = (
                sa.select(link.source_id, base.id, base.name)
                .select_from(
                    kb_base_sources.join(kb_bases, sa.and_(base.tenant_id == link.tenant_id, base.id == link.kb_id))
                )
                .where(link.tenant_id == tenant, link.source_id.in_(ids), team_visible(kb_base_sources))
                .where(team_visible(kb_bases))
                .order_by(link.source_id, link.kb_id)
            )
            feeds: dict[str, list[BaseName]] = {}
            for r in await c.execute(fed):
                feeds.setdefault(str(r.source_id), []).append(BaseName(id=r.id, name=r.name))
            going = sa.select(kb_runs.c.source_id).where(
                kb_runs.c.tenant_id == tenant,
                kb_runs.c.source_id.in_(ids),
                kb_runs.c.status == "running",
                team_visible(kb_runs),
            )
            running = {str(r[0]) for r in await c.execute(going.distinct())}
        found = [SourceRow.model_validate({**r, "item_counts": counts.get(str(r["id"]), {})}) for r in page["data"]]
        return SourcePage(page, found, feeds, running)

    async def links(self, tenant: str) -> list[tuple[str, str]]:
        """(knowledge base id, source id) for every attachment in the tenant."""
        async with self.tx() as c:
            q = sa.select(kb_base_sources.c.kb_id, kb_base_sources.c.source_id).where(
                kb_base_sources.c.tenant_id == tenant, team_visible(kb_base_sources)
            )
            return [(r.kb_id, r.source_id) for r in await c.execute(q)]

    async def create_base(self, row: dict[str, Any], source_ids: list[str]) -> None:
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    written = await one(c, sa.insert(kb_bases).values(**row).returning(*LABEL), BaseLabel)
            except IntegrityError as e:
                # An id is unique in the tenant; one another team holds is not seen before the insert.
                raise Conflict(f"A knowledge base with id {row['id']} already exists.") from e
            await self._link(c, row["tenant_id"], row["id"], source_ids)
            if written is not None:
                await _changed(c, row["tenant_id"], written)

    async def update_base(
        self, tenant: str, kb_id: str, values: dict[str, Any], *, audit: dict[str, Any] | None = None
    ) -> None:
        """`audit` is the change's entry for the account's audit log, written in the same transaction. A new name or
        colour raises the base's revision and reports `kb.changed`; the same name or colour sent again does neither."""
        key = (kb_bases.c.tenant_id == tenant, kb_bases.c.id == kb_id)
        async with self.tx() as c:
            relabel = False
            if "name" in values or "color" in values:
                q = sa.select(kb_bases.c.name, kb_bases.c.color).where(*key, team_visible(kb_bases))
                before = (await c.execute(q)).one_or_none()
                relabel = before is not None and (
                    values.get("name", before.name) != before.name or values.get("color", before.color) != before.color
                )
            if relabel:
                bumped = sa.update(kb_bases).where(*key).values(**values, revision=kb_bases.c.revision + 1)
                if (written := await one(c, bumped.returning(*LABEL), BaseLabel)) is not None:
                    await _changed(c, tenant, written)
            else:
                await c.execute(sa.update(kb_bases).where(*key).values(**values))
            if audit is not None:
                team = await self._team_of(c, kb_bases, tenant, kb_id)
                await record_audit(c, kb_outbox, tenant_id=tenant, team_id=team, **audit)

    async def attach(self, tenant: str, kb_id: str, source_ids: list[str]) -> None:
        async with self.tx() as c:
            await self._link(c, tenant, kb_id, source_ids)

    async def _link(self, c: AsyncConnection, tenant: str, kb_id: str, source_ids: list[str]) -> None:
        if not source_ids:
            return
        team = await self._team_of(c, kb_bases, tenant, kb_id)
        # One statement per source picked in a request (a handful); a link already there is left as it is.
        for s in dict.fromkeys(source_ids):
            link = {"tenant_id": tenant, "team_id": team, "kb_id": kb_id, "source_id": s}
            await c.execute(insert_ignore(c, kb_base_sources, link, keys=("tenant_id", "kb_id", "source_id")))

    async def create_source(self, row: dict[str, Any], kb_ids: list[str]) -> None:
        async with self.tx() as c:
            await c.execute(sa.insert(kb_sources).values(**row))
            for kb_id in kb_ids:
                await self._link(c, row["tenant_id"], kb_id, [row["id"]])

    async def remove_base(self, tenant: str, kb_id: str, *, by: str) -> bool:
        """Deletes the base and records its id as retired, in one transaction."""
        async with self.tx() as c:
            key = (kb_bases.c.tenant_id == tenant, kb_bases.c.id == kb_id)
            row = await one(c, sa.select(*LABEL).where(*key, team_visible(kb_bases)), BaseLabel)
            if row is None:
                return False
            await c.execute(sa.delete(kb_bases).where(*key))
            # One past its last write, so the delete is newer than every event about the base before it.
            await _changed(c, tenant, row, deleted=True)
            await c.execute(
                sa.insert(kb_retired_bases).values(
                    tenant_id=tenant,
                    team_id=row.team_id,
                    id=kb_id,
                    name=row.name,
                    retired_by=by,
                    retired_at=db_now(),
                )
            )
            return True

    async def retired(self, tenant: str, kb_ids: list[str] | None = None) -> set[str]:
        q = sa.select(kb_retired_bases.c.id).where(
            kb_retired_bases.c.tenant_id == tenant, team_visible(kb_retired_bases)
        )
        if kb_ids is not None:
            q = q.where(kb_retired_bases.c.id.in_(kb_ids))
        async with self.tx() as c:
            return {str(r.id) for r in await c.execute(q)}

    async def remove_source(self, tenant: str, source_id: str) -> bool:
        async with self.tx() as c:
            q = sa.delete(kb_sources).where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            return (await c.execute(q)).rowcount > 0

    # ── Items, versions and chunks ───────────────────────────────────────

    async def items(
        self, tenant: str, *, source_ids: list[str] | None = None, item_id: str | None = None
    ) -> list[ItemRow]:
        q = sa.select(*ITEM_COLUMNS).where(kb_items.c.tenant_id == tenant, team_visible(kb_items))
        if source_ids is not None:
            q = q.where(kb_items.c.source_id.in_(source_ids))
        if item_id is not None:
            q = q.where(kb_items.c.id == item_id)
        async with self.tx() as c:
            return await rows(c, q.order_by(kb_items.c.created_at, kb_items.c.id), ItemRow)

    async def versions(self, tenant: str, item_id: str) -> list[VersionRow]:
        v = kb_item_versions.c
        q = (
            sa.select(v.version, v.digest, v.status, v.allowed, v.created_at)
            .where(
                kb_item_versions.c.tenant_id == tenant,
                kb_item_versions.c.item_id == item_id,
                team_visible(kb_item_versions),
            )
            .order_by(kb_item_versions.c.version.desc())
        )
        async with self.tx() as c:
            return await rows(c, q, VersionRow)

    async def chunks(self, tenant: str, item_id: str) -> list[ChunkRow]:
        """The item's live chunks, in reading order."""
        q = (
            sa.select(
                kb_chunks.c.id,
                kb_chunks.c.position,
                kb_chunks.c.section,
                kb_chunks.c.page,
                kb_chunks.c.tokens,
                kb_chunks.c.text,
                kb_chunks.c.metadata,
            )
            .where(
                kb_chunks.c.tenant_id == tenant,
                kb_chunks.c.item_id == item_id,
                kb_chunks.c.withdrawn_at.is_(None),
                team_visible(kb_chunks),
            )
            .order_by(kb_chunks.c.position)
        )
        async with self.tx() as c:
            return await rows(c, q, ChunkRow)

    async def units(self, tenant: str, item_id: str) -> list[UnitRow]:
        """The index units of the item's live pieces: what each is searched as."""
        q = (
            sa.select(kb_units.c.chunk_id, kb_units.c.kind, kb_units.c.position, kb_units.c.text)
            .join(
                kb_chunks, sa.and_(kb_chunks.c.tenant_id == kb_units.c.tenant_id, kb_chunks.c.id == kb_units.c.chunk_id)
            )
            .where(
                kb_units.c.tenant_id == tenant,
                kb_units.c.item_id == item_id,
                kb_chunks.c.withdrawn_at.is_(None),
                team_visible(kb_units),
                team_visible(kb_chunks),
            )
            .order_by(kb_chunks.c.position, kb_units.c.position)
        )
        async with self.tx() as c:
            return await rows(c, q, UnitRow)

    async def index_version(
        self,
        tenant: str,
        item: dict[str, Any],
        version: dict[str, Any],
        chunks: list[PieceWrite],
        *,
        new: bool,
        change: dict[str, Any] | None = None,
    ) -> int | None:
        """Writes one version of an item with its chunks, and withdraws the previous version's chunks, in one
        transaction: a reader sees the old version or the new one, never both, and the change row lands with the
        version it records. Returns the version it replaced."""
        async with self.tx() as c:
            # The document, its version, chunks and change take its source's team.
            team = await self._team_of(c, kb_sources, tenant, str(item["source_id"]))
            item = {**item, "team_id": team}
            version = {**version, "team_id": team}
            stored, units = _with_team(chunks, team)
            change = {**change, "team_id": team} if change is not None else None
            replaced: int | None = None
            if new:
                await c.execute(sa.insert(kb_items).values(**item))
            else:
                key = (kb_items.c.tenant_id == tenant, kb_items.c.id == item["id"])
                replaced = (
                    await c.execute(sa.select(kb_items.c.version).where(*key, team_visible(kb_items)))
                ).scalar_one()
                await c.execute(sa.update(kb_items).where(*key).values(**item))
                await c.execute(
                    sa.update(kb_item_versions)
                    .where(kb_item_versions.c.tenant_id == tenant, kb_item_versions.c.item_id == item["id"])
                    .values(status="superseded")
                )
                stored, units = await _keep_unchanged(c, tenant, str(item["id"]), stored, units)
            await c.execute(sa.insert(kb_item_versions).values(**version))
            if stored:
                await c.execute(sa.insert(kb_chunks), stored)
            if units:
                await c.execute(sa.insert(kb_units), units)
            if change is not None:
                await c.execute(sa.insert(kb_changes).values(**change))
            return replaced

    async def purge_withdrawn(self, tenant: str, *, before: datetime) -> int:
        """Deletes pieces withdrawn before `before` (their units and vectors go with them); the number deleted. A
        version's text stays in its change row and its snapshot for as long as those are kept."""
        ch = kb_chunks
        async with self.tx() as c:
            done = await c.execute(
                sa.delete(ch).where(
                    ch.c.tenant_id == tenant,
                    ch.c.withdrawn_at.is_not(None),
                    ch.c.withdrawn_at < before,
                    team_visible(ch),
                )
            )
            return int(done.rowcount or 0)  # pyright: ignore[reportAttributeAccessIssue]

    async def mark_synced(self, tenant: str, source_id: str, status: str, *, activate: bool = False) -> int:
        """Records the run's outcome and the source's health: a success or partial run is a good sync and ends a
        failing streak; a failed one starts or lengthens it. `activate` moves a draft source to active in the same
        statement. Returns how many runs in a row have now failed."""
        good = status in ("success", "partial")
        src = kb_sources
        values: dict[str, Any] = {
            "last_sync_at": db_now(),
            "last_run_status": status,
            "last_good_sync_at": db_now() if good else src.c.last_good_sync_at,
            "failing_since": None if good else sa.func.coalesce(src.c.failing_since, db_now()),
            "failures_in_row": 0 if good else src.c.failures_in_row + 1,
        }
        if activate:
            values["status"] = sa.case((kb_sources.c.status == "draft", "active"), else_=kb_sources.c.status)
        async with self.tx() as c:
            await c.execute(
                sa.update(kb_sources)
                .where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
                .values(**values)
            )
            q = sa.select(src.c.failures_in_row).where(
                src.c.tenant_id == tenant, src.c.id == source_id, team_visible(src)
            )
            return int((await c.execute(q)).scalar_one_or_none() or 0)

    async def record_event(self, tenant: str, source_id: str, *, name: str, payload: dict[str, Any]) -> None:
        """A service event about the source (it keeps failing), relayed to agents-service so a workflow can act."""
        async with self.tx() as c:
            team = await self._team_of(c, kb_sources, tenant, source_id)
            await add_event(c, kb_outbox, tenant_id=tenant, team_id=team, name=name, key=new_id("evt"), payload=payload)

    @staticmethod
    async def _files_of(c: AsyncConnection, key: tuple[sa.ColumnElement[bool], ...]) -> sa.Row[Any, Any]:
        """A source's files and their names, its row locked until the transaction ends so two changes to its files
        never both read the old list."""
        await c.execute(locked(sa.select(kb_sources.c.id).where(*key, team_visible(kb_sources)), kb_sources))
        q = sa.select(kb_sources.c.file_ids, kb_sources.c.file_names).where(*key, team_visible(kb_sources))
        return (await c.execute(q)).one()

    async def add_file(self, tenant: str, source_id: str, file_id: str, name: str) -> None:
        async with self.tx() as c:
            key = (kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            row = await self._files_of(c, key)
            # A file uploaded under a name the source already holds is that document's next version: it takes the
            # earlier file's place, so a sync reads one file per document.
            known: dict[str, str] = dict(row.file_names or {})
            replaced = {f for f, n in known.items() if n == name and f != file_id}
            ids = [f for f in row.file_ids if f not in replaced]
            names = {f: n for f, n in known.items() if f not in replaced} | {file_id: name}
            await c.execute(
                sa.update(kb_sources)
                .where(*key)
                .values(file_ids=ids if file_id in ids else [*ids, file_id], file_names=names)
            )

    async def swap_files(self, tenant: str, source_id: str, moved: dict[str, str]) -> None:
        """Points a source at files copied to another store, keeping each file's place and uploaded name."""
        async with self.tx() as c:
            key = (kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            row = await self._files_of(c, key)
            held: list[str] = list(row.file_ids)
            given: dict[str, str] = dict(row.file_names or {})
            ids = [moved.get(f, f) for f in held]
            names = {moved.get(f, f): n for f, n in given.items()}
            await c.execute(sa.update(kb_sources).where(*key).values(file_ids=ids, file_names=names))

    async def drop_files(self, tenant: str, source_id: str, file_ids: set[str]) -> None:
        """Removes files from a source; the stored blobs stay, other sources may hold them."""
        if not file_ids:
            return
        async with self.tx() as c:
            key = (kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
            row = await self._files_of(c, key)
            kept: list[str] = [f for f in row.file_ids if f not in file_ids]
            names: dict[str, str] = row.file_names or {}
            await c.execute(
                sa.update(kb_sources)
                .where(*key)
                .values(file_ids=kept, file_names={f: n for f, n in names.items() if f in kept})
            )

    async def refreshed(self, tenant: str, kb_ids: list[str]) -> None:
        if not kb_ids:
            return
        async with self.tx() as c:
            await c.execute(
                sa.update(kb_bases)
                .where(kb_bases.c.tenant_id == tenant, kb_bases.c.id.in_(kb_ids))
                .values(last_refreshed_at=db_now())
            )

    async def reindex(self, tenant: str, item_id: str, values: dict[str, Any], chunks: list[PieceWrite]) -> None:
        """Rebuilds an item's chunks from the same content, keeping its version: the old chunks are withdrawn in the
        transaction that inserts the new ones."""
        async with self.tx() as c:
            team = await self._team_of(c, kb_items, tenant, item_id)
            stored, units = _with_team(chunks, team)
            await c.execute(
                sa.update(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.id == item_id).values(**values)
            )
            stored, units = await _keep_unchanged(c, tenant, item_id, stored, units)
            if stored:
                await c.execute(sa.insert(kb_chunks), stored)
            if units:
                await c.execute(sa.insert(kb_units), units)

    async def add_item(self, tenant: str, item: dict[str, Any]) -> None:
        """An item with no version yet (waiting for its reading, or failed before one), in its source's team."""
        async with self.tx() as c:
            team = await self._team_of(c, kb_sources, tenant, str(item["source_id"]))
            await c.execute(sa.insert(kb_items).values(**{**item, "team_id": team}))

    async def reading_items(self, tenant: str, *, file_id: str | None = None) -> list[ItemRow]:
        """The visible items waiting for their file's reading, one file's or all of them."""
        q = sa.select(*ITEM_COLUMNS).where(
            kb_items.c.tenant_id == tenant, kb_items.c.status == "reading", team_visible(kb_items)
        )
        if file_id is not None:
            q = q.where(kb_items.c.file_id == file_id)
        async with self.tx() as c:
            return await rows(c, q.order_by(kb_items.c.created_at, kb_items.c.id), ItemRow)

    async def update_item(self, tenant: str, item_id: str, values: dict[str, Any]) -> None:
        async with self.tx() as c:
            await c.execute(
                sa.update(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.id == item_id).values(**values)
            )

    async def update_source(
        self, tenant: str, source_id: str, values: dict[str, Any], *, audit: dict[str, Any] | None = None
    ) -> None:
        """`audit` is the change's entry for the account's audit log, written in the same transaction."""
        async with self.tx() as c:
            await c.execute(
                sa.update(kb_sources)
                .where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
                .values(**values)
            )
            if audit is not None:
                team = await self._team_of(c, kb_sources, tenant, source_id)
                await record_audit(c, kb_outbox, tenant_id=tenant, team_id=team, **audit)

    async def detach(self, tenant: str, kb_id: str, source_id: str) -> None:
        async with self.tx() as c:
            await c.execute(
                sa.delete(kb_base_sources).where(
                    kb_base_sources.c.tenant_id == tenant,
                    kb_base_sources.c.kb_id == kb_id,
                    kb_base_sources.c.source_id == source_id,
                )
            )

    async def remove_items(self, tenant: str, item_ids: list[str]) -> int:
        """Drops documents a tool source no longer lists, with their versions and chunks."""
        if not item_ids:
            return 0
        async with self.tx() as c:
            for table, column in (
                (kb_units, kb_units.c.item_id),
                (kb_chunks, kb_chunks.c.item_id),
                (kb_item_versions, kb_item_versions.c.item_id),
            ):
                await c.execute(sa.delete(table).where(table.c.tenant_id == tenant, column.in_(item_ids)))
            q = sa.delete(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.id.in_(item_ids))
            return (await c.execute(q)).rowcount

    async def claim(self, tenant: str, source_id: str, *, owner: str, seconds: float) -> bool:
        """Takes the source's sync lease for `owner` for `seconds` by the database's clock, when nobody holds it (or a
        holder's ran out): true when taken, so two syncs of one source never run at once."""
        s = kb_sources
        free = sa.or_(s.c.lease_until.is_(None), s.c.lease_until < db_now())
        async with self.tx() as c:
            q = (
                sa.update(s)
                .where(s.c.tenant_id == tenant, s.c.id == source_id, free, team_visible(s))
                .values(lease_until=db_after(seconds), lease_owner=owner)
            )
            return (await c.execute(q)).rowcount == 1

    async def renew(self, tenant: str, source_id: str, *, owner: str, seconds: float) -> bool:
        """Extends `owner`'s lease by `seconds` from now; false when it no longer holds it."""
        s = kb_sources
        async with self.tx() as c:
            q = (
                sa.update(s)
                .where(s.c.tenant_id == tenant, s.c.id == source_id, s.c.lease_owner == owner, team_visible(s))
                .values(lease_until=db_after(seconds))
            )
            return (await c.execute(q)).rowcount == 1

    async def release(self, tenant: str, source_id: str, *, owner: str) -> None:
        """Gives up `owner`'s lease; a lease another holder took is left alone."""
        async with self.tx() as c:
            await c.execute(_released(tenant, source_id, owner))

    async def add_run(self, row: dict[str, Any]) -> None:
        async with self.tx() as c:
            team = await self._team_of(c, kb_sources, str(row["tenant_id"]), str(row["source_id"]))
            await c.execute(sa.insert(kb_runs).values(**row, team_id=team))

    async def same_content(self, tenant: str, item_id: str, digest: str) -> list[SameText]:
        """Indexed items other than `item_id` with the same cleaned content, in a source read by any knowledge base
        that reads the item's source."""
        i, other, link, mine = kb_items, kb_items.alias("other"), kb_base_sources, kb_base_sources.alias("mine")
        bases = sa.select(mine.c.kb_id).where(mine.c.tenant_id == tenant, mine.c.source_id == other.c.source_id)
        q = (
            sa.select(i.c.id, i.c.title, i.c.source_id, i.c.processed_at)
            .join(link, (link.c.tenant_id == i.c.tenant_id) & (link.c.source_id == i.c.source_id))
            .join(other, (other.c.tenant_id == i.c.tenant_id) & (other.c.id == item_id))
            .where(
                i.c.tenant_id == tenant,
                i.c.id != item_id,
                i.c.content_digest == digest,
                i.c.status == "indexed",
                link.c.kb_id.in_(bases),
                team_visible(i),
            )
            .distinct()
        )
        async with self.tx() as c:
            return await rows(c, q, SameText)

    async def update_run(
        self, tenant: str, run_id: str, values: dict[str, Any], *, release: tuple[str, str] | None = None
    ) -> None:
        """`release` (source id, lease owner) frees the source in the same transaction, so a run seen finished never
        holds its source after."""
        async with self.tx() as c:
            await c.execute(
                sa.update(kb_runs).where(kb_runs.c.tenant_id == tenant, kb_runs.c.id == run_id).values(**values)
            )
            if release is not None:
                await c.execute(_released(tenant, *release))

    async def cancel_run(self, tenant: str, run_id: str, *, by: str) -> bool:
        """Asks a running run to stop; true when it was running and nobody had asked yet."""
        r = kb_runs
        async with self.tx() as c:
            q = (
                sa.update(r)
                .where(r.c.tenant_id == tenant, r.c.id == run_id, r.c.status == "running", r.c.cancelled_by.is_(None))
                .values(cancelled_by=by)
            )
            return (await c.execute(q)).rowcount == 1

    async def running_sources(self, tenant: str) -> set[str]:
        q = sa.select(kb_runs.c.source_id).where(
            kb_runs.c.tenant_id == tenant, kb_runs.c.status == "running", team_visible(kb_runs)
        )
        async with self.tx() as c:
            return {str(r[0]) for r in await c.execute(q.distinct())}

    async def end_stale_runs(self, tenant: str, *, reason: str) -> int:
        """Ends runs still marked running whose source's lease has lapsed: the process running them stopped, since a
        running sync or rebuild renews its lease for as long as it runs, however long that is."""
        r, s = kb_runs, kb_sources
        held = sa.exists().where(
            s.c.tenant_id == r.c.tenant_id,
            s.c.id == r.c.source_id,
            s.c.lease_until.is_not(None),
            s.c.lease_until >= db_now(),
        )
        async with self.tx() as c:
            q = (
                sa.update(r)
                .where(r.c.tenant_id == tenant, r.c.status == "running", ~held)
                .values(status="failed", finished_at=db_now(), log=[reason])
            )
            return int((await c.execute(q)).rowcount or 0)

    async def runs(
        self,
        tenant: str,
        *,
        source_id: str | None = None,
        source_ids: list[str] | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> list[RunRow]:
        """Runs newest first: of one source, of any of `source_ids`, or one run; `limit` keeps the newest."""
        shown = (col for col in kb_runs.c if col.name not in ("tenant_id", "team_id", "started_by"))
        q = sa.select(*shown).where(kb_runs.c.tenant_id == tenant, team_visible(kb_runs))
        if source_id is not None:
            q = q.where(kb_runs.c.source_id == source_id)
        if source_ids is not None:
            q = q.where(kb_runs.c.source_id.in_(source_ids))
        if limit is not None:
            q = q.limit(limit)
        if run_id is not None:
            q = q.where(kb_runs.c.id == run_id)
        async with self.tx() as c:
            return await rows(c, q.order_by(kb_runs.c.started_at.desc()), RunRow)

    async def run_page(self, tenant: str, source_id: str, params: ListParams) -> tuple[ListPage, list[RunRow]]:
        """One page of a source's runs, newest first, counted by status in SQL."""
        r = kb_runs.c
        shown = (col for col in kb_runs.c if col.name not in ("tenant_id", "team_id", "started_by"))
        q = sa.select(*shown).where(r.tenant_id == tenant, r.source_id == source_id, team_visible(kb_runs))
        async with self.tx() as c:
            page = await list_page(c, q, params, default_sort=r.started_at.desc(), facets={"status": r.status})
        return page, [RunRow.model_validate(row) for row in page["data"]]

    async def item_page(self, tenant: str, source_id: str, params: ListParams) -> tuple[ListPage, list[ItemRow]]:
        """One page of a source's documents, oldest first, searched by title or path and counted by status in SQL."""
        i = kb_items.c
        q = sa.select(*ITEM_COLUMNS).where(i.tenant_id == tenant, i.source_id == source_id, team_visible(kb_items))
        async with self.tx() as c:
            page = await list_page(
                c, q, params, search=[i.title, i.path], default_sort=i.created_at.asc(), facets={"status": i.status}
            )
        return page, [ItemRow.model_validate(row) for row in page["data"]]

    async def drafts(self, tenant: str, item_id: str) -> list[ChangeRow]:
        """The item's FAQ drafts in every state, oldest first."""
        c = kb_changes
        q = (
            sa.select(*CHANGE)
            .where(c.c.tenant_id == tenant, c.c.item_id == item_id, c.c.origin == "faq", team_visible(c))
            .order_by(c.c.changed_at, c.c.id)
        )
        async with self.tx() as conn:
            return await rows(conn, q, ChangeRow)

    async def add_drafts(self, tenant: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self.tx() as conn:
            team = await self._team_of(conn, kb_items, tenant, str(rows[0]["item_id"]))
            await conn.execute(sa.insert(kb_changes), [{**r, "tenant_id": tenant, "team_id": team} for r in rows])

    async def update_change(self, tenant: str, change_id: str, values: dict[str, Any]) -> None:
        c = kb_changes
        async with self.tx() as conn:
            await conn.execute(
                sa.update(c).where(c.c.tenant_id == tenant, c.c.id == change_id, team_visible(c)).values(**values)
            )

    async def replace_faq_units(self, tenant: str, item_id: str, units: list[dict[str, Any]]) -> None:
        """The item's approved FAQ pairs as units of its live pieces, in place of the ones it had."""
        u, ch = kb_units, kb_chunks
        live = sa.select(ch.c.id).where(
            ch.c.tenant_id == tenant, ch.c.item_id == item_id, ch.c.withdrawn_at.is_(None), team_visible(ch)
        )
        async with self.tx() as conn:
            await conn.execute(
                sa.delete(u).where(
                    u.c.tenant_id == tenant,
                    u.c.item_id == item_id,
                    u.c.kind == "faq",
                    u.c.chunk_id.in_(live),
                    team_visible(u),
                )
            )
            if units:
                team = await self._team_of(conn, kb_items, tenant, item_id)
                await conn.execute(sa.insert(u), [{**x, "tenant_id": tenant, "team_id": team} for x in units])

    async def changes(self, tenant: str, *, ids: list[str] | None = None) -> list[ChangeRow]:
        q = sa.select(*CHANGE).where(kb_changes.c.tenant_id == tenant, team_visible(kb_changes))
        if ids is not None:
            q = q.where(kb_changes.c.id.in_(ids))
        async with self.tx() as c:
            return await rows(c, q.order_by(kb_changes.c.changed_at.desc()), ChangeRow)

    async def change_page(
        self,
        tenant: str,
        *,
        view: str,
        owner: str,
        kb_id: str | None,
        search: str | None,
        origins: list[str] | None,
        page: int,
        page_size: int,
    ) -> ChangePage:
        """One page of the Changes queue, filtered, counted and paged in the database: `view` open (waiting for a
        decision), mine (waiting, on a source `owner` answers for), resolved or all; `kb_id` the changes of that base's
        sources; `search` in the title or section; `origins` (sync, faq) after the origin facet is counted."""
        c, s = kb_changes, kb_sources
        waiting = c.c.status.in_(DECIDABLE)
        mine = sa.and_(waiting, s.c.owner == owner)
        views: dict[str, sa.ColumnElement[bool]] = {
            "open": waiting,
            "mine": mine,
            "resolved": sa.not_(waiting),
            "all": sa.true(),
        }
        joined = c.outerjoin(s, sa.and_(s.c.tenant_id == c.c.tenant_id, s.c.id == c.c.source_id))
        scope: list[sa.ColumnElement[bool]] = [c.c.tenant_id == tenant, team_visible(c)]
        if kb_id is not None:
            linked = sa.select(kb_base_sources.c.source_id).where(
                kb_base_sources.c.tenant_id == tenant, kb_base_sources.c.kb_id == kb_id, team_visible(kb_base_sources)
            )
            scope.append(c.c.source_id.in_(linked))
        if search:
            scope.append(sa.or_(contains(c.c.title, search), contains(c.c.section, search)))
        shown = [*scope, views.get(view, sa.false())]
        listed = [*shown, c.c.origin.in_(origins)] if origins else shown

        def tally(when: sa.ColumnElement[bool]) -> sa.ColumnElement[Any]:
            return sa.func.coalesce(sa.func.sum(sa.case((when, 1), else_=0)), 0)

        async with self.tx() as conn:
            mine_n, open_n, done_n = (
                await conn.execute(
                    sa.select(tally(mine), tally(waiting), tally(sa.not_(waiting))).select_from(joined).where(*scope)
                )
            ).one()
            facet = {
                str(o): int(n)
                for o, n in await conn.execute(
                    sa.select(c.c.origin, sa.func.count()).select_from(joined).where(*shown).group_by(c.c.origin)
                )
            }
            total = int(await conn.scalar(sa.select(sa.func.count()).select_from(joined).where(*listed)) or 0)
            size = max(1, page_size)
            page = max(1, min(page, -(-total // size) or 1))
            q = (
                sa.select(*CHANGE)
                .select_from(joined)
                .where(*listed)
                .order_by(c.c.changed_at.desc(), c.c.id)
                .offset((page - 1) * size)
                .limit(size)
            )
            found = await rows(conn, q, ChangeRow)
        return ChangePage(found, total, {"mine": int(mine_n), "open": int(open_n), "resolved": int(done_n)}, facet)


# What `kb.changed` carries of a base: its label as other services show it.
LABEL = (kb_bases.c.id, kb_bases.c.team_id, kb_bases.c.name, kb_bases.c.color, kb_bases.c.revision)


class BaseLabel(Out):
    id: str
    team_id: str
    name: str
    color: str
    revision: int


async def _changed(c: AsyncConnection, tenant: str, row: BaseLabel, *, deleted: bool = False) -> None:
    """`kb.changed` on the outbox, in the transaction that made the change: the base's id, name, colour and
    revision, for the copies of the names other services keep (ops_store.copies)."""
    payload = KbChanged(id=row.id, name=row.name, colour=row.color, deleted=deleted)
    revision = row.revision + (1 if deleted else 0)
    event = Event(name="kb.changed", tenant_id=tenant, team_id=row.team_id, revision=revision, payload=payload)
    await add_event(c, kb_outbox, event)


def _released(tenant: str, source_id: str, owner: str) -> sa.Update:
    s = kb_sources
    return (
        sa.update(s)
        .where(s.c.tenant_id == tenant, s.c.id == source_id, s.c.lease_owner == owner, team_visible(s))
        .values(lease_until=None, lease_owner=None)
    )


def engine_for(url: str) -> AsyncEngine:
    return open_database(url)
