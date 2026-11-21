"""Migration 0123 adds the fair claim's columns to engine_work, the live queue, by failure mode: adding them waits for
the table's lock behind a claim still open and holds every later claim behind it, so the queue stalls until that claim
ends."""

from __future__ import annotations

import asyncio
import time

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from .test_drop_publish_policies import ROOT

BEFORE = "0122_run_failure_record"
CLAIM = sa.text("SELECT id FROM engine_work ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED")
# Past 0123's LOCK_TIMEOUT_MS (3 s): a claim that waits longer is held behind the migration.
CLAIM_WAITS_AT_MOST_S = 6.0


def test_adding_the_columns_never_holds_claims_behind_an_open_one(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)

    async def scenario() -> tuple[float, BaseException | None]:
        engine = create_async_engine(emptied_database)
        try:
            # A worker's claim, still open: the migration's exclusive lock waits for it.
            open_claim = await engine.connect()
            await open_claim.begin()
            await open_claim.execute(CLAIM)
            migrating = asyncio.create_task(asyncio.to_thread(command.upgrade, cfg, "head"))
            await asyncio.sleep(0.5)
            began = time.monotonic()
            try:
                async with engine.begin() as c:
                    await asyncio.wait_for(c.execute(CLAIM), CLAIM_WAITS_AT_MOST_S)
                waited = time.monotonic() - began
            except TimeoutError:
                waited = float("inf")
            finally:
                # Ending the open claim lets a migration still waiting on it finish, so the test never hangs.
                await open_claim.rollback()
                await open_claim.close()
            refused = (await asyncio.gather(migrating, return_exceptions=True))[0]
            return waited, refused if isinstance(refused, BaseException) else None
        finally:
            await engine.dispose()

    waited, refused = asyncio.run(scenario())
    assert waited < CLAIM_WAITS_AT_MOST_S, waited
    # It gave up on the lock rather than holding the queue, and runs once the claim has ended.
    assert refused is not None and "lock" in str(refused).lower(), refused
    command.upgrade(cfg, "head")
