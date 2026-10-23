"""The engine's tables, on their own MetaData. Migrations live in the host's chain (agents-service), which gives them
forced row-level security on `tenant_id` like its other tenant tables. Portable column types (JSON, not JSONB)."""

from __future__ import annotations

import sqlalchemy as sa

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED

metadata = sa.MetaData()

RUN_PREFIX = "wfrun_"
STAGES = ("draft", "live", "paused", "superseded")
# Bumped when a change to the compiler or wrapper would make a paused run resume differently.
ENGINE_BUILD = "1"

engine_definitions = sa.Table(
    "engine_definitions",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("workflow_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    # The definition as JSON, schemaVersion 2; YAML given on create is parsed before it is stored.
    sa.Column("definition", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("created_by", sa.String(200), nullable=False),
    # The team that owns the workflow; null for one the seed or a service published, which every team sees.
    sa.Column("team_id", sa.String(64)),
    # draft, live, paused or superseded (STAGES). At most one version of a workflow is live or paused; only that one
    # starts runs outside test mode. "In review" is not stored: it is a draft with an open publish request.
    sa.Column("stage", sa.String(16), nullable=False, server_default="draft"),
    # Set on every version when the workflow is archived (c-274): it starts no run of any mode and leaves the lists,
    # its versions and runs kept; restoring clears it.
    sa.Column("archived_at", sa.String(32)),
    sa.Column("archived_by", sa.String(200)),
    # One version per definition: publishing the same definition again returns its version.
    sa.UniqueConstraint("tenant_id", "workflow_id", "digest", name="uq_engine_definitions_digest"),
    info=TENANT_SCOPED,
)

# Live versions only, for a service event's listeners and the mailbox listener, which read nothing else from a table
# that keeps every version of every workflow (c-280). The same rows on PostgreSQL and SQL Server.
LIVE = engine_definitions.c.stage == "live"
sa.Index(
    "ix_engine_definitions_live",
    engine_definitions.c.tenant_id,
    engine_definitions.c.workflow_id,
    postgresql_where=LIVE,
    mssql_where=LIVE,
)

# One row per run. The id is also the run's thread id (lease, checkpoints, events) and carries RUN_PREFIX, so the v1
# sweeper can tell an engine thread from its own and leave it to the engine's worker.
engine_runs = sa.Table(
    "engine_runs",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    # No single-column index on tenant or workflow: every index below leads with tenant_id, and a lone tenant or
    # workflow index let the planner read a tenant's runs and sort them instead of the team's index in order (c-507).
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("workflow_id", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    # The caller's key for what started the run; a repeated key returns the first run.
    sa.Column("run_key", sa.String(200), nullable=False),
    sa.Column("mode", sa.String(8), nullable=False),
    # queued, running, waiting, succeeded, failed, cancelled
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("input", sa.JSON),
    sa.Column("outcome", sa.String(64)),
    sa.Column("output", sa.JSON),
    sa.Column("error", sa.Text),
    # While waiting: {node, iteration, interruptId, payload}; the Reviews facade reads it.
    sa.Column("waiting", sa.JSON),
    sa.Column("created_by", sa.String(200), nullable=False),
    # What carried a person's request when it was not the person (c-258): `event:<service>/<event>`. created_by stays
    # the person's email, so every rule on who started a run reads them.
    sa.Column("started_via", sa.String(200)),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    sa.Column("finished_at", sa.String(32)),
    sa.UniqueConstraint("tenant_id", "workflow_id", "run_key", name="uq_engine_runs_key"),
    # The runs list: one team's runs newest first, optionally by status, with a count per status (migration 0066).
    sa.Index("ix_engine_runs_team_created", "tenant_id", "team_id", "created_at"),
    sa.Index("ix_engine_runs_team_status_created", "tenant_id", "team_id", "status", "created_at"),
    # The runs list filtered by one workflow (c-280).
    sa.Index("ix_engine_runs_workflow_created", "tenant_id", "workflow_id", "created_at"),
    # The waiting or unfinished runs a run started, looked up on each child's status change to settle the parent.
    sa.Index("ix_engine_runs_parent_status", "tenant_id", "created_by", "status"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

# The step journal: one row per node attempt (journal.py).
engine_steps = sa.Table(
    "engine_steps",
    metadata,
    sa.Column("run_id", sa.String(64), primary_key=True),
    sa.Column("node_id", sa.String(80), primary_key=True),
    sa.Column("iteration", sa.Integer, primary_key=True),
    sa.Column("attempt", sa.Integer, primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("effects", sa.String(8), nullable=False),
    # The tool gateway's idempotency key for this attempt: run:node:iteration:attempt.
    sa.Column("key", sa.String(240), nullable=False),
    sa.Column("input", sa.JSON),
    sa.Column("port", sa.String(80)),
    sa.Column("output", sa.JSON),
    sa.Column("error", sa.Text),
    sa.Column("started_at", sa.String(32), nullable=False),
    sa.Column("finished_at", sa.String(32)),
    # The node's type id (ops.action.tool, ...), so a list of steps by kind needs no definition read; None before 0058.
    sa.Column("node_type", sa.String(80)),
    info=TENANT_SCOPED,
)

# The work queue: start, resume (a review decision), retry. Claimed with FOR UPDATE SKIP LOCKED, then the run's thread
# lease; a claim lapses at `lease_expires_at` unless its worker renews it, so a dead worker's row is claimed again.
engine_work = sa.Table(
    "engine_work",
    metadata,
    sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("payload", sa.JSON),
    # One row per thing that happened: a second decision of the same review finds the first.
    sa.Column("dedupe_key", sa.String(240), nullable=False),
    # queued, claimed, done, failed
    sa.Column("status", sa.String(16), nullable=False),
    # The engine build that may claim the row (workflow-runner.md section 7).
    sa.Column("build", sa.String(32), nullable=False),
    # Epoch seconds by the database's clock.
    sa.Column("available_at", sa.Float(), nullable=False),
    sa.Column("claimed_by", sa.String(120)),
    sa.Column("lease_expires_at", sa.Float()),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("error", sa.Text),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_engine_work_dedupe"),
    sa.Index("ix_engine_work_due", "status", "build", "available_at"),
    # The claim's other branch: claimed work whose lease lapsed (c-280).
    sa.Index("ix_engine_work_lease", "status", "build", "lease_expires_at"),
    info=TENANT_SCOPED,
)
