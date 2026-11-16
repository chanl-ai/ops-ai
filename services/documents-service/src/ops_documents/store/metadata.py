"""documents-service's tables, under their own migration chain (alembic_version_documents)."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.database import open_database, reachable

__all__ = ["RECOVER_PENDING", "ROLE", "SYSTEM_ROLE", "engine_for", "metadata", "reachable"]

metadata = sa.MetaData()
# The role every transaction runs as; row-level security applies to it (migration documents_0011).
ROLE = "ops_documents_tenant"
# The role a restart reads every tenant's queued work as, past row-level security; its grants name what it reads.
SYSTEM_ROLE = "ops_documents_system"
# Why the restart reads past the tenant: to pick up every tenant's queued reads and tests again.
RECOVER_PENDING = "recover_pending"


def engine_for(url: str) -> AsyncEngine:
    return open_database(url)
