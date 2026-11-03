"""platform-service's events reaching tools-service: a member removed from a team loses their own accounts
on that team's apps. By failure mode: the removed person's sign-ins stay, so their tokens work again if they come back;
someone else's sign-in in the team goes too, or the person's own in another team; any service may delete sign-ins; and
an event tools-service has no handler for fails, holding platform-service's outbox."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.platform_events import platform_events_router
from ops_identity import dev_service_signer, mint_service_token
from ops_tools.auth.tokens import Tokens
from ops_tools.platform_events import member_removed_handlers, team_created_handlers
from ops_tools.store.connections import ConnectionStore, connection_tokens
from ops_tools.store.modules import ModuleStore
from ops_tools.store.team_defaults import TeamDefaults

from .conftest import build_app, credentials

OPS, CARDS = "team_ops", "team_cards"
JAMES, MAYA = "usr_james", "usr_maya"


def platform(tenant: str, team: str, scopes: list[str]) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="platform", audience="tools", tenant_id=tenant, scopes=scopes, team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


async def keyed(store: ConnectionStore, tenant: str, team: str) -> str:
    """A connection of `team` each person signs in to with their own API key."""
    now, conn = datetime.now(UTC), f"con_{team}"
    row: dict[str, Any] = {
        "tenant_id": tenant,
        "id": conn,
        "team_id": team,
        "name": "Ledger",
        "auth_kind": "api_key",
        "sign_in": "person",
        "team_backup": False,
        "status": "healthy",
        "revision": 1,
        "created_by": "t",
        "created_at": now,
        "updated_by": "t",
        "updated_at": now,
    }
    assert await store.create(row, actor="t", at=now)
    plain = {"baseUrl": "https://ledger.bank.test", "name": "X-Api-Key"}
    await store.change(tenant, conn, 1, {}, actor="t", at=now, environment=("production", plain, {}))
    return conn


async def people(store: ConnectionStore, tenant: str, conn: str) -> list[str]:
    """Read past the store's team scope, which a request leaves set in this test's context."""
    t = connection_tokens.c
    async with store.engine.connect() as c:
        rows = await c.execute(sa.select(t.person_id).where(t.tenant_id == tenant, t.connection_id == conn))
        return sorted(str(r[0]) for r in rows)


async def test_a_removed_member_loses_their_accounts_on_that_teams_apps_only(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    store = ConnectionStore(engine)
    tokens = Tokens(store, credentials(), None, None)  # pyright: ignore[reportArgumentType]
    ops, cards = await keyed(store, tenant, OPS), await keyed(store, tenant, CARDS)
    for conn, person in ((ops, JAMES), (ops, MAYA), (cards, JAMES)):
        await tokens.store_own(tenant, conn, "production", person, {"key": f"key-{person}"})
    app = build_app(engine, seed, tenant)
    app.include_router(platform_events_router(member_removed_handlers(store, credentials())))
    body = {"name": "member.removed", "key": "mem_1:t", "teamId": OPS, "payload": {"personId": JAMES}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        refused = await c.post("/v1/platform-events", json=body, headers=platform(tenant, OPS, []))
        assert refused.status_code == 403, refused.text
        assert await people(store, tenant, ops) == [JAMES, MAYA]
        done = await c.post("/v1/platform-events", json=body, headers=platform(tenant, OPS, ["connections:delete"]))
        assert done.status_code == 200, done.text
        again = await c.post("/v1/platform-events", json=body, headers=platform(tenant, OPS, ["connections:delete"]))
        assert again.status_code == 200, "a repeat delivery is answered, never refused"
        other = {**body, "name": "team.renamed"}
        ignored = await c.post("/v1/platform-events", json=other, headers=platform(tenant, OPS, []))
        assert ignored.status_code == 200 and ignored.json()["data"]["handled"] is False, ignored.text
    assert await people(store, tenant, ops) == [MAYA]
    assert await people(store, tenant, cards) == [JAMES]


async def test_a_new_team_gets_its_built_in_apps_from_the_team_created_event(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    # PV2: the team's defaults are written when platform-service reports the team, before anyone opens it.
    store = ModuleStore(engine)
    app = build_app(engine, seed, tenant)
    app.include_router(platform_events_router(team_created_handlers(store, TeamDefaults(engine))))
    body = {"name": "team.created", "key": "team_new", "teamId": "team_new"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        refused = await c.post("/v1/platform-events", json=body, headers=platform(tenant, "team_new", []))
        assert refused.status_code == 403, refused.text
        done = await c.post("/v1/platform-events", json=body, headers=platform(tenant, "team_new", ["tools:create"]))
        assert done.status_code == 200 and done.json()["data"]["changed"] == 1, done.text
        again = await c.post("/v1/platform-events", json=body, headers=platform(tenant, "team_new", ["tools:create"]))
        assert again.status_code == 200 and again.json()["data"]["changed"] == 0, again.text
    made = await store.get(tenant, "mod_builtin_knowledge_team_new")
    assert made is not None and made["team_id"] == "team_new"
