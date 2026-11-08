"""A review opened by a service names the person who asked

Revision ID: 0099_review_asker_is_person
Revises: 0098_copies_record_digest

tools-service opens tool module reviews for the person who saved the module, and the request recorded
"tools-service on behalf of <person>" as its requester, which Human Tasks then showed as who asked. The requester is
now the person, and the service that opened it is kept in the request's body as openedBy. Rows written before move the
same way, in plain SQL per dialect so the revision renders offline. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from alembic import op

revision = "0099_review_asker_is_person"
down_revision = "0098_copies_record_digest"
branch_labels = None
depends_on = None

MARK = " on behalf of "
SERVICE_ASKED = f"requested_by LIKE '%-service{MARK}%'"

POSTGRES_UP = f"""
UPDATE registry_publish_requests
SET requested_by = split_part(requested_by, '{MARK}', 2),
    body = (
        COALESCE(body::jsonb, '{{}}'::jsonb) || jsonb_build_object('openedBy', split_part(requested_by, '{MARK}', 1))
    )::json
WHERE {SERVICE_ASKED}
"""
POSTGRES_DOWN = f"""
UPDATE registry_publish_requests
SET requested_by = (body::jsonb ->> 'openedBy') || '{MARK}' || requested_by,
    body = (body::jsonb - 'openedBy')::json
WHERE body::jsonb ? 'openedBy'
"""
# SQL Server reads every SET expression against the row as it was, so the requester is split before it is replaced.
MSSQL_UP = f"""
UPDATE registry_publish_requests
SET requested_by = SUBSTRING(requested_by, CHARINDEX('{MARK}', requested_by) + {len(MARK)}, 4000),
    body = JSON_MODIFY(COALESCE(body, '{{}}'), '$.openedBy', LEFT(requested_by, CHARINDEX('{MARK}', requested_by) - 1))
WHERE {SERVICE_ASKED}
"""
MSSQL_DOWN = f"""
UPDATE registry_publish_requests
SET requested_by = JSON_VALUE(body, '$.openedBy') + '{MARK}' + requested_by,
    body = JSON_MODIFY(body, '$.openedBy', NULL)
WHERE JSON_VALUE(body, '$.openedBy') IS NOT NULL
"""


def _mssql() -> bool:
    return op.get_context().dialect.name == "mssql"


def upgrade() -> None:
    op.execute(MSSQL_UP if _mssql() else POSTGRES_UP)


def downgrade() -> None:
    op.execute(MSSQL_DOWN if _mssql() else POSTGRES_DOWN)
