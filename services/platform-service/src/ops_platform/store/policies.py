"""The workspace's access policies at rest. A change writes the row, its audit entry and the tenant's next
permission version in one transaction, so a token minted after the change carries the new value and one minted before
it is refreshed by every service that caches on the version."""

from __future__ import annotations

from typing import Any, ClassVar, cast

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_access import BY_KEY, POLICIES, below_floor, check_value
from ops_access.platform_events import POLICY_CHANGED
from ops_access.policies import PUBLISH_AREAS
from ops_service_kit.http import Json, Out
from ops_service_kit.ids import now_iso
from ops_service_kit.narrow import json_object
from ops_store import Guarantee
from ops_store.dialect import insert_ignore
from ops_store.outbox import add as add_event
from ops_store.rows import rows

from .audit import record
from .roles import bump_version
from .tables import platform_outbox, policies
from .tenancy import TenantDb

OLD_KEYS = ("toolWritesNeedApproval", "appWritesNeedApproval", "appsChangeWithoutAsking")

# Each policy's value is free-form JSON (a switch, a number, a list, or a per-team object), keyed by policy: the shape a
# token carries in `Principal.policies` and `ops_access.policy()` reads.
PolicyValues = Json


class BelowFloorError(Exception):
    """A team's approval rule looser than the Security team's floor (`approvalsFloor`); the message says why."""


class PolicyRow(Out):
    key: str
    value: JsonValue


class PolicyStore(TenantDb):
    # `before` is read in the transaction that writes the change, so the audit entry and the row always agree.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    async def values(self, tenant_id: str) -> PolicyValues:
        """Every policy's value: what an admin set, else the catalogue's open default."""
        async with self.tenant_tx(tenant_id) as c:
            return await values_in(c)

    async def token_values(self, tenant_id: str) -> PolicyValues:
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
        async with self.tenant_tx(tenant_id) as c:
            row = (await c.execute(sa.select(policies.c.value).where(policies.c.key == key))).first()
            whole = row.value if row else spec.default
            after_of_team: Any = None
            if spec.per_team and key in ("requesterMayDecide", "appChanges", "appChangesByApp"):
                # Read in this transaction, so a floor set at the same moment is never missed.
                floor = (await c.execute(sa.select(policies.c.value).where(policies.c.key == "approvalsFloor"))).first()
                if (why := below_floor(key, value, floor.value if floor else None)) is not None:
                    raise BelowFloorError(why)
            if spec.per_team:
                whole = _by_team(whole, stored=row is not None)
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

    async def _team_part(self, tenant_id: str, key: str, team_id: str | None) -> dict[str, JsonValue]:
        if team_id is None:
            return {}
        async with self.tenant_tx(tenant_id) as c:
            row = (await c.execute(sa.select(policies.c.value).where(policies.c.key == key))).first()
        # No row: no team has a part yet. A catalogue default is never keyed by a team, so it holds none either.
        return json_object(json_object(row.value).get(team_id)) if row else {}

    async def _from_old_key(self, tenant_id: str, key: str, value: Any, team_id: str | None) -> tuple[str, Any]:
        """A write to an old key, as the new key's value for the same team: the old keys stay writable for one release
        and land in appChanges / appChangesByApp, which are the only stored truth."""
        if key == "toolWritesNeedApproval":
            held = await self._team_part(tenant_id, "appChanges", team_id)
            if value is True:
                return "appChanges", {**held, "ask": True, "answer": "reviewer"}
            # Off steps a reviewer down to the person who asked; it never switches asking off.
            if held.get("ask") and held.get("answer") == "reviewer":
                return "appChanges", {**held, "answer": "person"}
            return "appChanges", held
        apps = await self._team_part(tenant_id, "appChangesByApp", team_id)
        answer = "reviewer" if key == "appWritesNeedApproval" else "none"
        listed = [str(n) for n in cast(list[Any], value)] if isinstance(value, list) else []
        kept: dict[str, JsonValue] = {
            a: e for a, e in apps.items() if json_object(e).get("answer") != answer or a in listed
        }
        for app in listed:
            kept.setdefault(app, {"answer": answer})
        return "appChangesByApp", kept

    async def _derive_old_keys(self, c: AsyncConnection, tenant_id: str, team_id: str, by: str, at: str) -> None:
        """The old keys' value for one team, from appChanges and appChangesByApp, so a reader of the old keys sees
        what the new ones say. They are never read to decide a call."""

        async def part(key: str) -> dict[str, JsonValue]:
            row = (await c.execute(sa.select(policies.c.value).where(policies.c.key == key))).first()
            return json_object(row.value if row else {})

        team = json_object((await part("appChanges")).get(team_id))
        # A `tool:<name>` entry is one tool's answer, not an app: the old per-app lists never named it.
        apps = {
            a: json_object(e)
            for a, e in json_object((await part("appChangesByApp")).get(team_id)).items()
            if not a.startswith("tool:")
        }
        derived: PolicyValues = {
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


def _by_team(whole: Any, *, stored: bool) -> Any:
    """A per-team key's whole value as {team: part}. A value stored before the key was per team (requesterMayDecide
    true or false) held for every team, so it becomes the workspace's own part (`*`) and the teams that set nothing
    keep it; a catalogue default names no team."""
    if isinstance(whole, dict):
        return cast(Any, whole)
    return {"*": whole} if stored else {}


def new_workspace_values() -> PolicyValues:
    """What a workspace starts with when it is created: publishes go live at once, an app may call any public address,
    and a write its plugin or seed marked ask-first runs unless the team asks. Per-team values sit under `*`, the
    workspace's own part, so a team added later starts the same. Written as the workspace's own rows, so a workspace
    created before reads the catalogue default it always read; an admin turns each back on in Settings. Step-up needs
    no row: the catalogue has it off."""
    return {
        "publishReview": {"*": dict.fromkeys(PUBLISH_AREAS, "never")},
        "egressNewHosts": "any_public",
        "appChanges": {"*": {"makersAsk": False}},
    }


async def write_new_workspace_policies(c: AsyncConnection, tenant_id: str, *, at: str) -> None:
    """Inside the transaction that inserted the tenant row, and only then, so a later seed run never overwrites what an
    admin set since."""
    for key, wanted in new_workspace_values().items():
        # A per-team value is checked one team's part at a time, as a save through `set` checks it.
        value = (
            {team: check_value(key, part) for team, part in json_object(wanted).items()}
            if BY_KEY[key].per_team
            else check_value(key, wanted)
        )
        row = {"tenant_id": tenant_id, "key": key, "value": value, "updated_by": "workspace", "updated_at": at}
        await c.execute(insert_ignore(c, policies, row, keys=["tenant_id", "key"]))


async def values_in(c: AsyncConnection) -> PolicyValues:
    """`PolicyStore.values` on the caller's transaction."""
    held = {r.key: r.value for r in await rows(c, sa.select(policies.c.key, policies.c.value), PolicyRow)}
    return {p.key: held.get(p.key, p.default) for p in POLICIES}
