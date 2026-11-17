"""tenant_fences: a thread's write fence belongs to its tenant, and the database holds it there

gateway_fences was keyed by thread id alone, marked system and granted to ops_tools_tenant, so any tenant's transaction
read every tenant's thread ids and could raise another tenant's fence, refusing that tenant's writes. Each fence now
carries its tenant, is keyed by (tenant_id, thread_id) and is policed by tenant like the call log.

Backfill: a fence takes the tenant of the calls logged on its thread. A fence no call names (a takeover raised it
before the new owner wrote) is deleted: its tenant is unknown, so no tenant's read could find it. That is safe because
a fence only refuses a write whose generation is below it, every generation comes from agents' thread_leases, which
raises a thread's generation on each acquire and never restarts it, and agents-service is stopped for this step
(docs/deploy/database.md): no worker holding an older generation outlives the upgrade, and every lease taken after it
is above any fence ever raised. The new owner's next write raises it again. The one change a caller can see: a call
with no generation on such a thread, refused before, now passes, as on any thread no write has fenced. Downgrade
keeps one fence per thread, the highest generation, and puts back the thread-only key and the system marking.

Revision ID: tools_0082_tenant_fences
Revises: tools_0081_store_roles
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_predicates_ddl,
)

revision = "tools_0082_tenant_fences"
down_revision = "tools_0081_store_roles"
branch_labels = None
depends_on = None

CHAIN = "tools"
SYSTEM_USER = "ops_tools_system"
TABLE = "gateway_fences"
PKEY = "gateway_fences_pkey"


def _marked(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    fences = sa.table(TABLE, sa.column("thread_id", sa.String), sa.column("tenant_id", sa.String))
    calls = sa.table("gateway_calls", sa.column("thread_id", sa.String), sa.column("tenant_id", sa.String))
    op.add_column(TABLE, sa.Column("tenant_id", sa.String(64), nullable=True))
    # The call log is policed by tenant (tools_0080); the backfill reads every tenant's calls.
    before, after = backfill_ddl([_marked("gateway_calls")], dialect, chain=CHAIN, kind="tenant")
    for statement in before:
        op.execute(statement)
    owner = sa.select(sa.func.min(calls.c.tenant_id)).where(calls.c.thread_id == fences.c.thread_id)
    op.execute(sa.update(fences).values(tenant_id=owner.scalar_subquery()))
    op.execute(sa.delete(fences).where(fences.c.tenant_id.is_(None)))
    for statement in after:
        op.execute(statement)
    with op.batch_alter_table(TABLE) as b:
        b.alter_column("tenant_id", existing_type=sa.String(64), nullable=False)
        b.drop_constraint(PKEY, type_="primary")
        b.create_primary_key(PKEY, ["tenant_id", "thread_id"])
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(
            CHAIN, [_marked(TABLE)], column_type=_column_type, system_user=SYSTEM_USER
        ):
            op.execute(statement)
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_ddl(_marked(TABLE), dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(TABLE), dialect):
            op.execute(statement)
    fences = sa.table(
        TABLE,
        sa.column("thread_id", sa.String),
        sa.column("tenant_id", sa.String),
        sa.column("generation", sa.BigInteger),
    )
    other = fences.alias("other")
    # One fence per thread: the highest generation, ties broken by tenant, so the thread-only key holds.
    beaten = sa.exists().where(
        other.c.thread_id == fences.c.thread_id,
        sa.or_(
            other.c.generation > fences.c.generation,
            sa.and_(other.c.generation == fences.c.generation, other.c.tenant_id > fences.c.tenant_id),
        ),
    )
    op.execute(sa.delete(fences).where(beaten))
    with op.batch_alter_table(TABLE) as b:
        b.drop_constraint(PKEY, type_="primary")
        b.create_primary_key(PKEY, ["thread_id"])
        b.drop_column("tenant_id")
