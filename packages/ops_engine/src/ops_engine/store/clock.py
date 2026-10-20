"""Times the queue compares are the database's (`now()`), never a process clock, as for leases (ADR-0016)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection


def db_now(conn: AsyncConnection) -> Any:
    if conn.dialect.name == "postgresql":
        return sa.func.extract("epoch", sa.func.now())
    return (sa.func.julianday("now") - 2440587.5) * 86400.0


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
