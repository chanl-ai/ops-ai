"""A review opened by a service names the person who asked

Revision ID: 0099_review_asker_is_person
Revises: 0098_copies_record_digest

tools-service opens tool module reviews for the person who saved the module, and the request recorded
"tools-service on behalf of <person>" as its requester, which Human Tasks then showed as who asked. The requester is
now the person, and the service that opened it is kept in the request's body as openedBy. Rows written before move the
same way. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0099_review_asker_is_person"
down_revision = "0098_copies_record_digest"
branch_labels = None
depends_on = None

MARK = " on behalf of "
requests = sa.table(
    "registry_publish_requests",
    sa.column("tenant_id", sa.String),
    sa.column("id", sa.String),
    sa.column("requested_by", sa.String),
    sa.column("body", sa.JSON),
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(requests.c.tenant_id, requests.c.id, requests.c.requested_by, requests.c.body).where(
            requests.c.requested_by.like(f"%-service{MARK}%")
        )
    ).all()
    for tenant, rid, by, body in rows:
        service, person = str(by).split(MARK, 1)
        held: dict[str, Any] = json.loads(body) if isinstance(body, str) else dict(body or {})
        bind.execute(
            requests.update()
            .where(requests.c.tenant_id == tenant, requests.c.id == rid)
            .values(requested_by=person, body={**held, "openedBy": service})
        )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(requests.c.tenant_id, requests.c.id, requests.c.requested_by, requests.c.body)).all()
    for tenant, rid, by, body in rows:
        held: dict[str, Any] = json.loads(body) if isinstance(body, str) else dict(body or {})
        service = held.pop("openedBy", None)
        if service:
            bind.execute(
                requests.update()
                .where(requests.c.tenant_id == tenant, requests.c.id == rid)
                .values(requested_by=f"{service}{MARK}{by}", body=held)
            )
