"""LangGraph's own checkpointer conformance suite (langgraph-checkpoint-conformance) run against AsyncpgSaver."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

from langgraph.checkpoint.conformance import (  # pyright: ignore[reportMissingTypeStubs]
    checkpointer_test,
    validate,
)

from ops_checkpointer import RLS_ROLE, AsyncpgSaver, create_pool
from ops_checkpointer.saver import asyncpg_dsn


async def test_langgraph_conformance(database_url: str) -> None:
    pool = await create_pool(asyncpg_dsn(database_url), max_size=4)

    # A tenant per suite, so the suites that list across every thread see only their own rows.
    @checkpointer_test(name="AsyncpgSaver")
    async def saver() -> AsyncGenerator[AsyncpgSaver]:
        yield AsyncpgSaver(pool, tenant_id=f"conf-{uuid4().hex}", team_id="team", role=RLS_ROLE)

    try:
        report = await validate(saver)
    finally:
        await pool.close()
    report.print_report()
    assert report.passed_all_base()
    assert report.passed_all()
