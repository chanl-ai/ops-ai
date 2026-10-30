"""The one place the Runtime chooses its checkpointer. Swapping the saver implementation is a change to this file."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from ops_checkpointer import open_saver

from ..store.tenancy import LOCAL_TENANT

__all__ = ["LOCAL_TENANT", "open_checkpointer"]


def open_checkpointer(database_url: str) -> AbstractAsyncContextManager[BaseCheckpointSaver[Any]]:
    # The tenant and team are read per transaction from the request's or loop's isolation context, so one compiled
    # graph serves every tenant and team; a run acts as its thread's team (api/runs.py), and a write with none is
    # refused.
    return open_saver(database_url)
