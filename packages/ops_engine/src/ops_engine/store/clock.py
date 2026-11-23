"""Times the queue compares are the database's (`now()`), never a process clock, as for leases (ADR-0016)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ops_store.dialect import db_epoch


def db_now(conn: AsyncConnection) -> Any:
    """Epoch seconds on the database's clock, on every database ops_store supports."""
    return db_epoch()


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
