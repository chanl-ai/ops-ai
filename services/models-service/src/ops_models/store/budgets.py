"""Budgets: a conversation's, run's, step's, group's, eval run's or draft's caps on cost, calls and tokens, what was
spent against them, and the reservations of the calls in flight. Every read and write names the tenant and runs as
ROLE in it, so the database holds each row to its tenant.

A call reserves its estimate on each budget it names before the provider is called, in id order, with one conditional
update per budget that names the caps it must still be under (DA12): a row count of 0 is the refusal, so two calls at
the same moment cannot both take the last room. A refusal of a later budget gives back the earlier ones in the same
transaction. A call past its caps is admitted only for its one closing call or its capped check calls, counted on the
budget per replay key. The call then settles to its actual usage, or is released when it fails.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.http import Out
from ops_service_kit.ids import new_id
from ops_store import Guarantee
from ops_store.dialect import db_now, insert_ignore, locked
from ops_store.rows import one, rows
from ops_store.store import Store

from .provider_keys import ROLE
from .tables import model_budget_reservations as holds_t
from .tables import model_budgets as t

Limit = Literal["cost", "calls", "tokens"]
# How many replay keys a budget remembers for its closing and check calls past the caps.
KEPT_KEYS = 20


class BudgetRow(Out):
    """A budget as stored."""

    id: str
    kind: str
    parent_id: str | None
    team_id: str
    created_by: str
    max_cost: Decimal | None
    max_calls: int | None
    max_tokens: int | None
    spent_cost: Decimal
    spent_calls: int
    spent_tokens: int
    reserved_cost: Decimal
    reserved_calls: int
    reserved_tokens: int
    expires_at: datetime | None
    updated_at: datetime

    @property
    def exhausted(self) -> Limit | None:
        """The first cap already reached by what was spent."""
        if self.max_cost is not None and self.spent_cost >= self.max_cost:
            return "cost"
        if self.max_calls is not None and self.spent_calls >= self.max_calls:
            return "calls"
        if self.max_tokens is not None and self.spent_tokens >= self.max_tokens:
            return "tokens"
        return None


SHOWN = (
    t.c.id,
    t.c.kind,
    t.c.parent_id,
    t.c.team_id,
    t.c.created_by,
    t.c.max_cost,
    t.c.max_calls,
    t.c.max_tokens,
    t.c.spent_cost,
    t.c.spent_calls,
    t.c.spent_tokens,
    t.c.reserved_cost,
    t.c.reserved_calls,
    t.c.reserved_tokens,
    t.c.expires_at,
    t.c.updated_at,
)


@dataclass(frozen=True)
class BudgetFields:
    """What a PUT sets. The caps and expiry change on a repeat; kind, parent, team and creator are the first PUT's."""

    kind: str
    parent_id: str | None
    team_id: str
    created_by: str
    max_cost: Decimal | None
    max_calls: int | None
    max_tokens: int | None
    expires_at: datetime | None


@dataclass(frozen=True)
class Ask:
    """What one call asks of each budget it names: its estimate, its purpose, and the replay key its closing and
    check calls past the caps are counted under."""

    cost: Decimal
    tokens: int
    purpose: str = "turn"
    replay_key: str | None = None
    # How many check or judge calls a replay key may make past a spent budget.
    check_calls: int = 0


@dataclass(frozen=True)
class Hold:
    """One call's reservation on one budget: what settle and release give back."""

    id: str
    budget_id: str
    cost: Decimal
    tokens: int


@dataclass(frozen=True)
class BudgetRefusal:
    """Why a call's reservation was refused: the status and code it is answered with, and the budget's limit."""

    status: int
    code: str
    budget_id: str
    limit: Limit | None = None
    spent: Decimal | int | None = None
    cap: Decimal | int | None = None


@dataclass(frozen=True)
class Reserved:
    holds: list[Hold]
    refusal: BudgetRefusal | None = None


def _limit(row: Any, cost: Decimal, tokens: int) -> tuple[Limit, Decimal | int, Decimal | int]:
    """The cap the estimate does not fit under, with what was spent and the cap."""
    if row.max_cost is not None and row.spent_cost + row.reserved_cost + cost > row.max_cost:
        return "cost", Decimal(row.spent_cost), Decimal(row.max_cost)
    if row.max_calls is not None and row.spent_calls + row.reserved_calls + 1 > row.max_calls:
        return "calls", int(row.spent_calls), int(row.max_calls)
    return "tokens", int(row.spent_tokens), int(row.max_tokens or 0)


class Budgets(Store):
    role = ROLE
    # Reserve is one conditional update per budget, and a call's reservations, refusal and releases land together.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    async def put(self, tenant_id: str, budget_id: str, fields: BudgetFields) -> BudgetRow:
        """Creates the budget, or moves its caps and expiry; spend never changes here."""
        mine = (t.c.tenant_id == tenant_id, t.c.id == budget_id)
        caps = {
            "max_cost": fields.max_cost,
            "max_calls": fields.max_calls,
            "max_tokens": fields.max_tokens,
            "expires_at": fields.expires_at,
        }
        change = t.update().where(*mine).values(**caps, updated_at=db_now())
        first: dict[str, Any] = {
            "tenant_id": tenant_id,
            "id": budget_id,
            "kind": fields.kind,
            "parent_id": fields.parent_id,
            "team_id": fields.team_id,
            "created_by": fields.created_by,
            "closing_keys": [],
            "check_calls": {},
            **caps,
        }
        async with self.tx() as c:
            # An update, then the first insert, then the update again when a concurrent PUT inserted it first.
            if (
                not (await c.execute(change)).rowcount
                and not (await c.execute(insert_ignore(c, t, first, keys=["tenant_id", "id"]))).rowcount
            ):
                await c.execute(change)
            found = await one(c, sa.select(*SHOWN).where(*mine), BudgetRow)
        if found is None:
            raise LookupError(f"no budget {budget_id} for the tenant after it was saved")
        return found

    async def get(self, tenant_id: str, budget_id: str) -> BudgetRow | None:
        async with self.tx() as c:
            return await one(c, sa.select(*SHOWN).where(t.c.tenant_id == tenant_id, t.c.id == budget_id), BudgetRow)

    async def query(self, tenant_id: str, ids: Sequence[str]) -> list[BudgetRow]:
        """The budgets of `ids` the tenant holds, by id, in one statement; an unknown id is left out."""
        q = sa.select(*SHOWN).where(t.c.tenant_id == tenant_id, t.c.id.in_(sorted(set(ids)))).order_by(t.c.id)
        async with self.tx() as c:
            return await rows(c, q, BudgetRow)

    async def reserve(self, tenant_id: str, ids: Sequence[str], ask: Ask, *, expires_at: datetime) -> Reserved:
        """Reserves one call and its estimate on each budget of `ids`, in id order, in the open transaction. The first
        budget that cannot cover it refuses the call, and the ones reserved before it are given back."""
        holds: list[Hold] = []
        # A closing key or check count is written only once every budget admitted the call, so a refusal on a later
        # budget leaves the earlier one's key unspent.
        counts: list[sa.Update] = []
        async with self.tx() as c:
            for budget_id in sorted(set(ids)):
                if not await self._take(c, tenant_id, budget_id, ask):
                    past = await self._past_caps(c, tenant_id, budget_id, ask)
                    if isinstance(past, BudgetRefusal):
                        await self._give_back(c, tenant_id, holds)
                        return Reserved([], past)
                    counts.append(past)
                hold = Hold(new_id("rsv"), budget_id, ask.cost, ask.tokens)
                await c.execute(
                    holds_t.insert().values(
                        id=hold.id,
                        budget_id=budget_id,
                        tenant_id=tenant_id,
                        cost=ask.cost,
                        calls=1,
                        tokens=ask.tokens,
                        expires_at=expires_at,
                    )
                )
                holds.append(hold)
            for count in counts:
                await c.execute(count)
        return Reserved(holds)

    async def _take(self, c: AsyncConnection, tenant_id: str, budget_id: str, ask: Ask, *, capped: bool = True) -> bool:
        """The reserve statement: the room it needs is in its WHERE clause, so a concurrent reserve that took the
        last of it leaves this one matching no row."""
        cost, tokens = ask.cost, ask.tokens
        q = t.update().where(t.c.tenant_id == tenant_id, t.c.id == budget_id)
        if capped:
            q = q.where(
                sa.or_(t.c.max_cost.is_(None), t.c.spent_cost + t.c.reserved_cost + cost <= t.c.max_cost),
                sa.or_(t.c.max_calls.is_(None), t.c.spent_calls + t.c.reserved_calls + 1 <= t.c.max_calls),
                sa.or_(t.c.max_tokens.is_(None), t.c.spent_tokens + t.c.reserved_tokens + tokens <= t.c.max_tokens),
            )
        q = q.values(
            reserved_cost=t.c.reserved_cost + cost,
            reserved_calls=t.c.reserved_calls + 1,
            reserved_tokens=t.c.reserved_tokens + tokens,
            updated_at=db_now(),
        )
        return bool((await c.execute(q)).rowcount)

    async def _past_caps(
        self, c: AsyncConnection, tenant_id: str, budget_id: str, ask: Ask
    ) -> BudgetRefusal | sa.Update:
        """A budget that could not cover the call: 404 when the tenant has none by that id; when the call is the
        replay key's closing call or one of its capped check calls, reserved past the caps, and the statement that
        counts it on the budget, for `reserve` to run once every budget admitted it; else the refusal naming the cap.
        The row stays locked until the transaction ends."""
        q = sa.select(t).where(t.c.tenant_id == tenant_id, t.c.id == budget_id)
        row = (await c.execute(locked(q, t))).first()
        if row is None:
            return BudgetRefusal(404, "budget_not_found", budget_id)
        limit, spent, cap = _limit(row, ask.cost, ask.tokens)
        refused = BudgetRefusal(429, "budget_reached", budget_id, limit, spent, cap)
        key = ask.replay_key or ""
        mine = (t.c.tenant_id == tenant_id, t.c.id == budget_id)
        if ask.purpose == "closing":
            kept: list[Any] = list(row.closing_keys or [])
            closed = [str(k) for k in kept]
            if key in closed:
                return refused
            count = t.update().where(*mine).values(closing_keys=[*closed, key][-KEPT_KEYS:])
        elif ask.purpose in ("check", "judge"):
            calls: dict[Any, Any] = dict(row.check_calls or {})
            counted = {str(k): int(v) for k, v in calls.items()}
            if counted.get(key, 0) >= ask.check_calls:
                return BudgetRefusal(429, "check_cap_reached", budget_id, limit, spent, cap)
            counted[key] = counted.pop(key, 0) + 1
            count = t.update().where(*mine).values(check_calls=dict(list(counted.items())[-KEPT_KEYS:]))
        else:
            return refused
        await self._take(c, tenant_id, budget_id, ask, capped=False)
        return count

    async def settle(self, tenant_id: str, holds: Sequence[Hold], *, cost: Decimal, tokens: int) -> None:
        """Replaces each reservation with the call's actual cost and tokens, in the open transaction; a reservation
        already settled or released adds nothing."""
        async with self.tx() as c:
            for hold in sorted(holds, key=lambda h: h.budget_id):
                if await self._drop(c, tenant_id, hold):
                    await c.execute(
                        t.update()
                        .where(t.c.tenant_id == tenant_id, t.c.id == hold.budget_id)
                        .values(
                            spent_cost=t.c.spent_cost + cost,
                            spent_calls=t.c.spent_calls + 1,
                            spent_tokens=t.c.spent_tokens + tokens,
                            **_unreserved(hold),
                        )
                    )

    async def release(self, tenant_id: str, holds: Sequence[Hold]) -> None:
        """Gives back each reservation of a call that failed; one already settled or released adds nothing."""
        async with self.tx() as c:
            await self._give_back(c, tenant_id, holds)

    async def _give_back(self, c: AsyncConnection, tenant_id: str, holds: Sequence[Hold]) -> None:
        for hold in sorted(holds, key=lambda h: h.budget_id):
            if await self._drop(c, tenant_id, hold):
                await c.execute(
                    t.update().where(t.c.tenant_id == tenant_id, t.c.id == hold.budget_id).values(**_unreserved(hold))
                )

    async def _drop(self, c: AsyncConnection, tenant_id: str, hold: Hold) -> bool:
        """Deletes the reservation's row; whether it was still there, which is what lets the budget move."""
        gone = holds_t.delete().where(holds_t.c.tenant_id == tenant_id, holds_t.c.id == hold.id)
        return bool((await c.execute(gone)).rowcount)


def _unreserved(hold: Hold) -> dict[str, Any]:
    return {
        "reserved_cost": t.c.reserved_cost - hold.cost,
        "reserved_calls": t.c.reserved_calls - 1,
        "reserved_tokens": t.c.reserved_tokens - hold.tokens,
        "updated_at": db_now(),
    }
