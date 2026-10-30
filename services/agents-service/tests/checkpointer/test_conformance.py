"""LangGraph's own checkpointer conformance suite (langgraph-checkpoint-conformance) run against CheckpointSaver."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

from langgraph.checkpoint.conformance import (  # pyright: ignore[reportMissingTypeStubs]
    checkpointer_test,
    validate,
)

from ops_checkpointer import RLS_ROLE, CheckpointSaver
from ops_store.database import open_database


async def test_langgraph_conformance(database_url: str) -> None:
    db = open_database(database_url, pool_size=4)

    # A tenant per suite, so the suites that list across every thread see only their own rows.
    @checkpointer_test(name="CheckpointSaver")
    async def saver() -> AsyncGenerator[CheckpointSaver]:
        yield CheckpointSaver(db, tenant_id=f"conf-{uuid4().hex}", team_id="team", role=RLS_ROLE)

    try:
        report = await validate(saver)
    finally:
        await db.dispose()
    report.print_report()
    assert report.passed_all_base()
    assert report.passed_all()
