"""The checkpointer's three tables as SQLAlchemy metadata, the one source of their schema: the SQL Server bundle is
compiled from it, and the agents chain's PostgreSQL migrations (0004, 0008, 0071, 0090) are held equal to it by
deploy/database/tests/test_model_parity.py. Key columns are bounded, since SQL Server refuses VARCHAR(max) in a key."""

from __future__ import annotations

import sqlalchemy as sa

from ops_store.dialect import db_now
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED

metadata = sa.MetaData()


ops_checkpoints = sa.Table(
    "ops_checkpoints",
    metadata,
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("checkpoint_ns", sa.String(255), nullable=False, server_default=""),
    sa.Column("checkpoint_id", sa.String(64), nullable=False),
    sa.Column("parent_checkpoint_id", sa.Text()),
    sa.Column("type", sa.Text(), nullable=False),
    sa.Column("checkpoint", sa.LargeBinary(), nullable=False),
    sa.Column("metadata_type", sa.Text(), nullable=False),
    sa.Column("metadata_blob", sa.LargeBinary(), nullable=False),
    sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    # The one metadata key a query filters on (deleting a run's checkpoints), as its own column so every database can
    # index it; other keys are filtered after reading.
    sa.Column("run_id", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
    sa.PrimaryKeyConstraint("tenant_id", "team_id", "thread_id", "checkpoint_ns", "checkpoint_id"),
    sa.Index("ix_ops_checkpoints_run", "tenant_id", "team_id", "run_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

ops_checkpoint_writes = sa.Table(
    "ops_checkpoint_writes",
    metadata,
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("checkpoint_ns", sa.String(255), nullable=False, server_default=""),
    sa.Column("checkpoint_id", sa.String(64), nullable=False),
    sa.Column("task_id", sa.String(64), nullable=False),
    sa.Column("idx", sa.Integer(), nullable=False),
    sa.Column("channel", sa.Text(), nullable=False),
    sa.Column("type", sa.Text(), nullable=False),
    sa.Column("blob", sa.LargeBinary(), nullable=False),
    sa.Column("task_path", sa.Text(), nullable=False, server_default=""),
    sa.PrimaryKeyConstraint("tenant_id", "team_id", "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

# Each writer's fence: the highest lease generation it has seen per thread; a write below it is refused (ADR-0016).
ops_checkpoint_fences = sa.Table(
    "ops_checkpoint_fences",
    metadata,
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("generation", sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint("tenant_id", "team_id", "thread_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)
