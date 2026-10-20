"""The workspace's access policies at rest (c-186). A change writes the row, its audit entry and the tenant's next
permission version in one transaction, so a token minted after the change carries the new value and one minted before
it is refreshed by every service that caches on the version."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_access import BY_KEY, POLICIES, check_value
from ops_service_kit.ids import now_iso
from ops_store import Guarantee

from .audit import record
from .roles import bump_version
from .tables import policies
from .tenancy import TenantDb


class PolicyStore:
    # `before` is read in the transaction that writes the change, so the audit entry and the row always agree.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def values(self, tenant_id: str) -> dict[str, Any]:
        """Every policy's value: what an admin set, else the catalogue's open default."""
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(sa.select(policies.c.key, policies.c.value))).all()
        held = {r.key: r.value for r in rows}
        return {p.key: held.get(p.key, p.default) for p in POLICIES}

    async def token_values(self, tenant_id: str) -> dict[str, Any]:
        """The values a token carries: every policy but those read live on each decision (`live`, publishReview)."""
        values = await self.values(tenant_id)
        return {k: v for k, v in values.items() if not BY_KEY[k].live}

    async def set(
        self, tenant_id: str, key: str, value: Any, *, by: str, request_id: str, team_id: str | None = None
    ) -> tuple[Any, Any]:
        """Stores the value; returns (before, after). A per-team key (`publishReview`) takes `team_id` and replaces that
        team's part only, read and written in one transaction, so a save never touches another team's. ValueError for
        an unknown key or a value the policy does not take, before anything is written."""
        value = check_value(key, value)
        spec = BY_KEY[key]
        if spec.per_team and not team_id:
            raise ValueError(f"{key} is set per team; choose a team")
        at = now_iso()
        async with self.db.tenant_tx(tenant_id) as c:
            row = (await c.execute(sa.select(policies.c.value).where(policies.c.key == key))).first()
            whole = row.value if row else spec.default
            after_of_team: Any = None
            if spec.per_team:
                before = dict(whole).get(team_id)
                value = {**dict(whole), str(team_id): value}
                after_of_team = value[str(team_id)]
            else:
                before = whole
            if row is None:
                await c.execute(
                    policies.insert().values(tenant_id=tenant_id, key=key, value=value, updated_by=by, updated_at=at)
                )
            else:
                await c.execute(
                    policies.update().where(policies.c.key == key).values(value=value, updated_by=by, updated_at=at)
                )
            await bump_version(c, tenant_id)
            await record(
                c,
                tenant_id=tenant_id,
                team_id=team_id if spec.per_team else None,
                actor=by,
                action="policy.set",
                target_kind="policy",
                target_id=key,
                request_id=request_id,
                detail={"before": before, "after": after_of_team if spec.per_team else value},
            )
        return before, (after_of_team if spec.per_team else value)
