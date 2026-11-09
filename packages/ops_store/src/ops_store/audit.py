"""One audit log for every service. A service records a change's audit entry in its own outbox, in the transaction
that makes the change, and its relay delivers the entry to platform-service's POST /v1/audit-events, which keeps the
account's one audit log that the Audit page reads. The change and its entry commit together; the entry reaches the log
once platform-service answers, at least once, and platform-service keeps one row per entry id.

  await record(conn, outbox, tenant_id=..., team_id=..., actor=principal.sub, action="knowledge.source.settings",
               target_kind="knowledge_source", target_id=source_id, summary="Changed ...", detail={...})
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from .outbox import add

# The outbox event an audit entry travels as; its key is the entry's id.
AUDIT_EVENT = "audit.recorded"
# Where a relay delivers it on platform-service's internal port.
AUDIT_ROUTE = "/v1/audit-events"
# The scope a relay's service token holds to write the account's audit log.
AUDIT_SCOPE = "audit:create"


async def record(
    conn: AsyncConnection,
    outbox: sa.Table,
    *,
    tenant_id: str,
    team_id: str,
    actor: str,
    action: str,
    target_kind: str,
    target_id: str,
    summary: str,
    detail: dict[str, Any],
    request_id: str | None = None,
) -> str:
    """Writes the entry on the caller's connection, so it commits with the change it records; returns its id.
    `summary` is the one line the Audit page shows, since platform-service cannot word another service's action."""
    entry_id = f"aud_{uuid.uuid4().hex}"
    payload = {
        "action": action,
        "targetKind": target_kind,
        "targetId": target_id,
        "requestId": request_id or entry_id,
        "detail": {**detail, "summary": summary},
    }
    await add(conn, outbox, tenant_id=tenant_id, team_id=team_id, name=AUDIT_EVENT, key=entry_id, payload=payload,
              actor=actor)  # fmt: skip
    return entry_id
