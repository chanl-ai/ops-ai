"""One provider subject per person, and the flow columns that link a person from their session or invite

A first sign-in linked a new provider subject to whichever person had the email, so one person could collect several
subjects at the same provider, each a way into their account. `uq_signin_identities_person` allows one subject per
person per provider. Where a person already holds more than one, the most recently used link is kept (latest
`last_used_at`, then `created_at`, then the highest id) and the others are deleted. Each deleted link is recorded
first as a `signin.unlink` audit entry naming the tenant, the person and the subject (and logged when the upgrade runs
online), and every session those people hold is ended, since any of them may have been opened through a link that is
now gone. A single link made by email before this rule stays as it is. The writes run with each table's isolation
policy set aside (`backfill_ddl`), so they see every tenant's rows, not none.

`signin_flows.subject` keeps a link flow's provider subject until the session that started it completes the link;
`signin_flows.invite_hash` names the invite a sign-in started from. The downgrade drops all three; deleted links and
ended sessions stay gone.

Revision ID: 20261123_2330_identity_per_user
Revises: 20261122_2022_list_sort_indexes
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "20261123_2330_identity_per_user"
down_revision = "20261122_2022_list_sort_indexes"
branch_labels = None
depends_on = None

CHAIN = "platform"
log = logging.getLogger("alembic.runtime.migration")

# A link that is not its person's most recently used one at that provider; the same text on both dialects.
LATER = (
    "EXISTS (SELECT 1 FROM signin_identities o"
    " WHERE o.tenant_id = s.tenant_id AND o.provider_id = s.provider_id AND o.user_id = s.user_id"
    " AND (o.last_used_at > s.last_used_at"
    "  OR (o.last_used_at = s.last_used_at AND o.created_at > s.created_at)"
    "  OR (o.last_used_at = s.last_used_at AND o.created_at = s.created_at AND o.id > s.id)))"
)
# A JSON string's characters: a backslash and a double quote escaped, as a subject may hold either.
_SUBJECT = "REPLACE(REPLACE(s.subject, '\\', '\\\\'), '\"', '\\\"')"


def _audit(dialect: str, at: str) -> str:
    detail = f'CONCAT(\'{{"provider": "\', s.provider_id, \'", "subject": "\', {_SUBJECT}, \'", "how": "migration"}}\')'
    if dialect == "postgresql":
        detail = f"CAST({detail} AS JSON)"
    return (
        "INSERT INTO audit_entries (id, tenant_id, team_id, actor, action, target_kind, target_id, request_id, at,"
        f" detail) SELECT CONCAT('aud_', s.id), s.tenant_id, NULL, 'migration', 'signin.unlink', 'user', s.user_id,"
        f" '{revision[:64]}', '{at}', {detail} FROM signin_identities s WHERE {LATER}"
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    policed = [
        sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)
        for name in ("signin_identities", "sessions", "audit_entries")
    ]
    before, after = backfill_ddl(policed, dialect, chain=CHAIN, kind="tenant")
    for statement in before:
        op.execute(statement)
    if not op.get_context().as_sql:
        later = sa.text(f"SELECT s.tenant_id, s.user_id, s.subject FROM signin_identities s WHERE {LATER}")
        for tenant, person, subject in op.get_bind().execute(later).all():
            log.warning("signin link removed: tenant=%s person=%s subject=%s", tenant, person, subject)
    op.execute(_audit(dialect, at))
    op.execute(
        f"UPDATE sessions SET revoked_at = '{at}' WHERE revoked_at IS NULL AND user_id IN"
        f" (SELECT s.user_id FROM signin_identities s WHERE {LATER})"
    )
    op.execute(f"DELETE FROM signin_identities WHERE id IN (SELECT s.id FROM signin_identities s WHERE {LATER})")
    for statement in after:
        op.execute(statement)
    op.create_unique_constraint(
        "uq_signin_identities_person", "signin_identities", ["tenant_id", "provider_id", "user_id"]
    )
    op.add_column("signin_flows", sa.Column("subject", sa.String(255), nullable=True))
    op.add_column("signin_flows", sa.Column("invite_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("signin_flows", "invite_hash")
    op.drop_column("signin_flows", "subject")
    op.drop_constraint("uq_signin_identities_person", "signin_identities", type_="unique")
