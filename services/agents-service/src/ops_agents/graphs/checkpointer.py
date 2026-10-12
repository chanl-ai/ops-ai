"""The one place the Runtime chooses its checkpointer. Swapping the saver implementation is a change to this file."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from ops_checkpointer import open_saver

from ..store.tenancy import LOCAL_TENANT, current_tenant

# The checkpoint key's team part. Team access is decided by the API before a thread is touched; what isolates rows at
# rest is the tenant, which RLS on the checkpoint tables checks (0004).
LOCAL_TEAM = "local"
__all__ = ["LOCAL_TEAM", "LOCAL_TENANT", "open_checkpointer"]


def open_checkpointer(database_url: str) -> AbstractAsyncContextManager[BaseCheckpointSaver[Any]]:
    # The tenant is read per transaction from the request's or loop's scope, so one compiled graph serves every tenant.
    return open_saver(database_url, tenant_id=current_tenant, team_id=LOCAL_TEAM)
