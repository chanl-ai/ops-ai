"""The workspace's access policies at rest. A change writes the row, its audit entry and the tenant's next
permission version in one transaction, so a token minted after the change carries the new value and one minted before
it is refreshed by every service that caches on the version."""

from __future__ import annotations

from typing import Any, ClassVar, cast

import sqlalchemy as sa

from ops_access import BY_KEY, POLICIES, check_value
from ops_access.platform_events import POLICY_CHANGED
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.dialect import insert_ignore
from ops_store.outbox import add as add_event

from .audit import record
from .roles import bump_version
from .tables import platform_outbox, policies
from .tenancy import TenantDb

OLD_KEYS = ("toolWritesNeedApproval", "appWritesNeedApproval", "appsChangeWithoutAsking")


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
        if BY_KEY[key].per_team and not team_id:
            raise ValueError(f"{key} is set per team; choose a team")
        if key in OLD_KEYS:
            key, value = await self._from_old_key(tenant_id, key, value, team_id)
            value = check_value(key, value)
        spec = BY_KEY[key]
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
            if key in ("appChanges", "appChangesByApp"):
                await self._derive_old_keys(c, tenant_id, str(team_id), by, at)
                # Agents-service keeps each team's tool list, which carries every write's answer, for up to 30 s: it
                # drops that list when it hears this, so the change applies at once.
                await add_event(
                    c, platform_outbox, tenant_id=tenant_id, team_id=str(team_id), name=POLICY_CHANGED,
                    key=f"{key}:{request_id}:{at}", payload={"key": key}, actor=by,
                )  # fmt: skip
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

    async def _team_part(self, tenant_id: str, key: str, team_id: str | None) -> Any:
        async with self.db.tenant_tx(tenant_id) as c:
            row = (await c.execute(sa.select(policies.c.value).where(policies.c.key == key))).first()
        return dict(row.value if row else BY_KEY[key].default).get(team_id)

    async def _from_old_key(self, tenant_id: str, key: str, value: Any, team_id: str | None) -> tuple[str, Any]:
        """A write to an old key, as the new key's value for the same team: the old keys stay writable for one release
        and land in appChanges / appChangesByApp, which are the only stored truth."""
        if key == "toolWritesNeedApproval":
            held = dict(await self._team_part(tenant_id, "appChanges", team_id) or {})
            if value is True:
                return "appChanges", {**held, "ask": True, "answer": "reviewer"}
            # Off steps a reviewer down to the person who asked; it never switches asking off.
            if held.get("ask") and held.get("answer") == "reviewer":
                return "appChanges", {**held, "answer": "person"}
            return "appChanges", held
        apps = dict(await self._team_part(tenant_id, "appChangesByApp", team_id) or {})
        answer = "reviewer" if key == "appWritesNeedApproval" else "none"
        listed = [str(n) for n in cast(list[Any], value)] if isinstance(value, list) else []
        kept: dict[str, Any] = {a: e for a, e in apps.items() if e.get("answer") != answer or a in listed}
        for app in listed:
            kept.setdefault(app, {"answer": answer})
        return "appChangesByApp", kept

    async def _derive_old_keys(self, c: Any, tenant_id: str, team_id: str, by: str, at: str) -> None:
        """The old keys' value for one team, from appChanges and appChangesByApp, so a reader of the old keys sees
        what the new ones say. They are never read to decide a call."""

        async def part(key: str) -> dict[str, Any]:
            row = (await c.execute(sa.select(policies.c.value).where(policies.c.key == key))).first()
            return dict(row.value if row else {})

        team = dict((await part("appChanges")).get(team_id) or {})
        # A `tool:<name>` entry is one tool's answer, not an app: the old per-app lists never named it.
        apps = {
            a: e
            for a, e in dict((await part("appChangesByApp")).get(team_id) or {}).items()
            if not a.startswith("tool:")
        }
        derived: dict[str, Any] = {
            "toolWritesNeedApproval": bool(team.get("ask")) and team.get("answer") == "reviewer",
            "appWritesNeedApproval": [a for a, e in apps.items() if e.get("answer") == "reviewer"],
            "appsChangeWithoutAsking": [a for a, e in apps.items() if e.get("answer") == "none"],
        }
        for old, new in derived.items():
            whole = {**await part(old), team_id: new}
            if (await c.execute(sa.select(policies.c.key).where(policies.c.key == old))).first() is None:
                await c.execute(
                    policies.insert().values(tenant_id=tenant_id, key=old, value=whole, updated_by=by, updated_at=at)
                )
            else:
                await c.execute(
                    policies.update().where(policies.c.key == old).values(value=whole, updated_by=by, updated_at=at)
                )


def new_workspace_values() -> dict[str, Any]:
    """What a workspace starts with when it is created: an app may call any public address, and a write its plugin or
    seed marked ask-first runs unless the team asks. Per-team values sit under `*`, the workspace's own part, so a team
    added later starts the same. Written as the workspace's own rows, so a workspace created before reads the catalogue
    default it always read; an admin turns each back on in Settings. Step-up needs no row: the catalogue has it off.
    publishReview has no row either: a first publish or a major change waits for a second person (the catalogue's
    `major`, roles-and-permissions.md E01) from the workspace's first day."""
    return {
        "egressNewHosts": "any_public",
        "appChanges": {"*": {"makersAsk": False}},
    }


async def write_new_workspace_policies(c: Any, tenant_id: str, *, at: str) -> None:
    """Inside the transaction that inserted the tenant row, and only then, so a later seed run never overwrites what an
    admin set since."""
    for key, wanted in new_workspace_values().items():
        # A per-team value is checked one team's part at a time, as a save through `set` checks it.
        value = (
            {team: check_value(key, part) for team, part in wanted.items()}
            if BY_KEY[key].per_team
            else check_value(key, wanted)
        )
        row = {"tenant_id": tenant_id, "key": key, "value": value, "updated_by": "workspace", "updated_at": at}
        await c.execute(insert_ignore(c, policies, row, keys=["tenant_id", "key"]))
