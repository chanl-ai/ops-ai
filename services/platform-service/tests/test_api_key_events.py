"""Every API key write reports `api_key.changed` in its own transaction, for agents-service's copy of the keys, by
failure mode: a write path that reports nothing (the copy stays stale until its next resync), a report at a revision
that does not rise (a copy keeps the older state), a rolled-back write that still reports, a report carrying the
secret's hash, and a summary whose revision is not the event's (each resync would set the copy back)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from ops_access import ANY_TEAM
from ops_platform.api_keys import summary
from ops_platform.store.key_events import change_keys
from ops_platform.store.keys import KeyStore
from ops_platform.store.lifecycle import LifecycleStore
from ops_platform.store.relay import ROUTE, platform_relay
from ops_platform.store.tables import api_keys, platform_outbox, role_assignments
from ops_platform.store.tenancy import TenantDb
from ops_service_kit.ids import new_id

from .conftest import Platform
from .test_api_keys import create
from .test_member_removed_event import Client
from .test_members import as_admin, join, member_rows

AT = "2026-01-01T00:00:00.000Z"
# What an event carries of a key: never its secret's hash, scopes or creator.
CARRIED = {
    "kind", "id", "name", "prefix", "status", "targetKind", "targetId", "targetVersion", "createdAt", "lastUsedAt",
    "expiresAt", "deleted", "revision",
}  # fmt: skip


async def events(platform: Platform, tenant: str) -> list[tuple[str, int, str, str]]:
    """(key, revision, status, team) per `api_key.changed`, oldest first."""
    async with platform.engine.connect() as c:
        q = (
            sa.select(platform_outbox.c.team_id, platform_outbox.c.event_key, platform_outbox.c.payload)
            .where(platform_outbox.c.tenant_id == tenant, platform_outbox.c.name == "api_key.changed")
            .order_by(platform_outbox.c.created_at, platform_outbox.c.id)
        )
        found = (await c.execute(q)).all()
    out: list[tuple[str, int, str, str]] = []
    for team, key, payload in found:
        assert key == f"{payload['id']}@{payload['revision']}" and set(payload) == CARRIED, payload
        out.append((str(payload["id"]), int(payload["revision"]), str(payload["status"]), str(team)))
    return out


async def test_each_key_write_reports_the_key_once_at_a_rising_revision(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    team, tenant = h["X-Team-Id"], admin.tenant_id
    mine = str((await create(platform, h))["key"]["id"])  # type: ignore[index]
    # A second admin's key, which stops when they are removed from the team (I10).
    other = await join(platform, admin, "admin")
    token = (await platform.sign_in(other)).json()["data"]["token"]
    theirs = str((await create(platform, {"Authorization": f"Bearer {token}", "X-Team-Id": team}))["key"]["id"])  # type: ignore[index]
    assert (await platform.public.post(f"/v1/api-keys/{mine}/revoke", headers=h)).status_code == 200
    assert (await platform.public.post(f"/v1/api-keys/{mine}/revoke", headers=h)).status_code == 200  # no change
    [row] = [r for r in await member_rows(platform, h, role="admin") if r["email"] == other.email]
    r = await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": [row["id"]]})
    assert r.json()["data"]["updated"] == [row["id"]], r.text
    live = str((await create(platform, h))["key"]["id"])  # type: ignore[index]
    # Closing disables every key not yet disabled (the revoked one too); restoring enables only those again.
    store = LifecycleStore(TenantDb(platform.engine))
    owner = admin.user_id
    async with platform.engine.begin() as c:
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"), tenant_id=tenant, subject_kind="person", subject_id=owner, role_id="owner",
                team_id=ANY_TEAM, granted_by="test", reason="owner", source="grant", created_at=AT,
            )
        )  # fmt: skip
    await store.close(tenant, by=owner, at=AT, request_id="req_close")
    await store.restore(tenant, by=owner, request_id="req_restore")
    assert sorted(await events(platform, tenant)) == sorted([
        (mine, 1, "active", team), (mine, 2, "revoked", team), (mine, 3, "revoked", team), (mine, 4, "revoked", team),
        (theirs, 1, "active", team), (theirs, 2, "disabled", team),
        (live, 1, "active", team), (live, 2, "disabled", team), (live, 3, "active", team),
    ])  # fmt: skip
    # The summaries another service resyncs from state each key's last event's revision.
    async with platform.engine.connect() as c:
        held = dict((await c.execute(sa.select(api_keys.c.id, api_keys.c.revision))).all())
    assert {k: held[k] for k in (mine, theirs, live)} == {mine: 4, theirs: 2, live: 3}
    summaries = [summary(k) for k in await KeyStore(TenantDb(platform.engine)).every(tenant)]
    assert {s["id"]: s["revision"] for s in summaries} == {mine: 4, theirs: 2, live: 3}
    # The relay sends each one to agents-service in the key's tenant and team.
    agents = Client()
    relay = platform_relay(platform.engine, {"agents": agents})
    while await relay.once():
        pass
    mine_sent = [(b["key"], t) for p, b, tenant_of, t in agents.sent if tenant_of == tenant and p == ROUTE]
    assert sorted(k for k, _ in mine_sent) == sorted(f"{k}@{r}" for k, r, _, _ in await events(platform, tenant))
    assert {t for _, t in mine_sent} == {team}


async def test_a_key_write_that_rolls_back_reports_nothing(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    made = str((await create(platform, h))["key"]["id"])  # type: ignore[index]
    before = await events(platform, admin.tenant_id)
    with pytest.raises(RuntimeError):
        async with TenantDb(platform.engine).tenant_tx(admin.tenant_id) as c:
            assert await change_keys(c, api_keys.c.id == made, {"disabled_at": AT}) == [made]
            raise RuntimeError("the change it belongs to failed")
    assert await events(platform, admin.tenant_id) == before == [(made, 1, "active", h["X-Team-Id"])]
