"""A model call's charge, written to every ledger at once, and its replay from the log when no settle wrote it.

The provider bills a call before models-service records it. When the settle and its fallback both fail (the database
is gone right after the provider answered), or the server stops before a settle ends, the call's whole charge is logged
at error level as one record (`model_call_row_lost`, `model_call_settle_unfinished_at_stop`), and nothing is written.
An operator replays those lines once the database is back:

    uv run python -m ops_models.recovery < lines.jsonl

The call's id is the row's primary key, and a replay writes the row first, so a replay of a call already charged (a
settle whose commit landed though it reported a failure, or a line replayed twice) writes nothing and adds no spend.

Log lines mask personal data, so a value holding an email or a long run of digits reaches the log masked (`[email]`,
`[account]`): a `user:<email>` key's id, a model name with a date in it. Such a line is never replayed, since it would
charge an id that does not exist or write a wrong value: it is counted and logged (`model_call_charge_unreplayable`).
The operator puts the real values back in the line (from the key list and the alias's version) and replays it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterable

from pydantic import ValidationError

from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.database import Database, open_database

from .app import Charge, charge
from .store import CallLog, ModelKeys

log = get_logger(__name__)

# The log lines that carry a charge nothing durable recorded.
REPLAYABLE = frozenset({"model_call_row_lost", "model_call_settle_unfinished_at_stop"})


# What ops_pii.mask writes in place of personal data: an id holding one is not the id the call was made with.
_MASKED = ("[email]", "[SSN]", "[card]", "[phone]", "[account]", "[redacted]")


def masked(call: Charge) -> bool:
    """Whether the log masked any text this charge is written with (an id, a model name with a date in it)."""
    return any(isinstance(v, str) and any(m in v for m in _MASKED) for v in call.row.values())


async def replay(db: Database, call: Charge) -> bool:
    """Charges a call no settle recorded. False, and nothing written, when its row is there: it was charged. The row
    is written as the tenant it names and no other, and whether the key spends per tenant is read from the key, never
    taken from the line. A key that does not exist, or one that spends per tenant on a row naming no tenant, raises
    `Unreplayable`."""
    keys = ModelKeys(db)
    key = await keys.get(call.row["key_id"])
    if key is None:
        raise Unreplayable("its key does not exist")
    per_tenant = key.tenant_budget is not None
    if per_tenant and not call.row["tenant_id"]:
        raise Unreplayable("its key spends per tenant and the row names no tenant")
    async with isolation.request_transaction():
        return await charge(keys, CallLog(db), call.model_copy(update={"per_tenant": per_tenant}), once=True)


class Unreplayable(Exception):
    """A line that cannot be charged as it stands."""


async def replay_lines(db: Database, lines: Iterable[str]) -> tuple[int, int, int]:
    """Replays every replayable record among `lines` (the service's JSON log); returns (charged, already charged,
    not replayable because the log masked an id)."""
    charged = skipped = refused = 0
    for text in lines:
        if not text.startswith("{"):
            continue
        line = json.loads(text)
        if line.get("event") not in REPLAYABLE:
            continue
        try:
            call = Charge.model_validate(line)
        except ValidationError:
            refused += 1
            log.error("model_call_charge_unreplayable", call_id=line.get("call_id"), why="the line has no whole charge")
            continue
        if masked(call):
            refused += 1
            log.error("model_call_charge_unreplayable", call_id=call.row["id"], why="a value was masked in the log")
            continue
        try:
            done = await replay(db, call)
        except Unreplayable as e:
            refused += 1
            log.error("model_call_charge_unreplayable", call_id=call.row["id"], why=str(e))
            continue
        if done:
            charged += 1
        else:
            skipped += 1
    return charged, skipped, refused


def main() -> None:
    settings = Settings()
    configure_logging(service="models-service")
    db = open_database(settings.database_url)

    async def run() -> None:
        try:
            charged, skipped, refused = await replay_lines(db, sys.stdin)
            log.info("model_call_charges_replayed", charged=charged, already_charged=skipped, not_replayable=refused)
        finally:
            await db.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
