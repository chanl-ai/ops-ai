"""The sign-in keep-alive, by failure mode: a sign-in left unused past the idle limit is never refreshed, so the system
ends it (Salesforce's 30 days) and a monthly agent fails; one used recently is refreshed for nothing; a refresh the
system refuses because the grant ended leaves the account reading as connected; a passing fault on one sign-in marks it
broken or stops the pass; and only the first team's sign-ins are kept, another team's left to lapse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.auth import Authenticator
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.keepalive import REFRESH_AFTER, SignInKeepalive
from ops_tools.connections.records import account_state
from ops_tools.store.connections import SHARED, ConnectionStore, connection_tokens
from ops_tools.store.team_defaults import TeamDefaults

from .conftest import credentials
from .test_personal_sign_in import TEAM, AnyUrl, connection

OTHER = "team_cards"


class System:
    """The system's token address: each refresh token it is sent is refreshed, refused as an ended grant, or answered
    with a passing fault, by the refresh token's own name."""

    def __init__(self) -> None:
        self.refreshed: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        sent = dict(parse_qsl(request.content.decode())).get("refresh_token", "")
        if sent.startswith("rt-ended"):
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired refresh token"})
        if sent.startswith("rt-flaky"):
            return httpx.Response(503, json={"error": "temporarily_unavailable"})
        self.refreshed.append(sent)
        return httpx.Response(200, json={"access_token": f"at-new-{sent}", "expires_in": 3600})


def rig(engine: AsyncEngine, system: System) -> tuple[ConnectionStore, Tokens, SignInKeepalive]:
    store = ConnectionStore(engine)
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(system.handle))
    tokens = Tokens(store, credentials(), upstream, AnyUrl())  # pyright: ignore[reportArgumentType]
    return store, tokens, SignInKeepalive(TeamDefaults(engine), store, Authenticator(store, None, tokens))


async def _held(
    engine: AsyncEngine, tokens: Tokens, tenant: str, conn: str, refresh: str, *, idle: timedelta, person: str = SHARED
) -> None:
    """A sign-in holding `refresh`, last refreshed `idle` ago."""
    await tokens.store_answer(
        tenant, conn, {"access_token": f"at-{refresh}", "expires_in": 3600, "refresh_token": refresh}, person
    )
    t = connection_tokens.c
    async with engine.begin() as c:
        await c.execute(
            connection_tokens.update()
            .where(t.tenant_id == tenant, t.connection_id == conn, t.person_id == person)
            .values(refreshed_at=datetime.now(UTC) - idle)
        )


async def _teams(engine: AsyncEngine, tenant: str, *teams: str) -> None:
    for team in teams:
        await TeamDefaults(engine).record(tenant, team, 1, datetime.now(UTC))


IDLE = REFRESH_AFTER + timedelta(days=1)


async def test_a_sign_in_left_unused_is_refreshed_and_a_recent_one_is_not(engine: AsyncEngine, tenant: str) -> None:
    system = System()
    store, tokens, keepalive = rig(engine, system)
    await _teams(engine, tenant, TEAM)
    idle, used = await connection(store, tenant, "team"), await connection(store, tenant, "person")
    await _held(engine, tokens, tenant, idle, "rt-idle", idle=IDLE)
    await _held(engine, tokens, tenant, used, "rt-used", idle=timedelta(days=2))
    await _held(engine, tokens, tenant, used, "rt-james", idle=IDLE, person="usr_james")
    assert await keepalive.once() == 2
    assert sorted(system.refreshed) == ["rt-idle", "rt-james"], system.refreshed
    row = await store.token(tenant, idle)
    assert row is not None and row["rotations"] == 2 and row["refreshed_at"] > datetime.now(UTC) - timedelta(minutes=1)


async def test_an_ended_grant_marks_the_account_for_a_reconnect(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, keepalive = rig(engine, System())
    await _teams(engine, tenant, TEAM)
    conn = await connection(store, tenant, "person_or_team")
    await _held(engine, tokens, tenant, conn, "rt-ended-team", idle=IDLE)
    await _held(engine, tokens, tenant, conn, "rt-ended-james", idle=IDLE, person="usr_james")
    assert await keepalive.once() == 0
    account = await store.get(tenant, conn)
    assert account is not None and account["status"] == "needs_reconnect", account
    assert account_state(account, await store.token(tenant, conn), datetime.now(UTC)) == "refused"
    james = await store.token(tenant, conn, "usr_james")
    assert james is not None and james["refused_at"] is not None, james


async def test_a_passing_fault_leaves_the_account_and_the_pass_goes_on(engine: AsyncEngine, tenant: str) -> None:
    system = System()
    store, tokens, keepalive = rig(engine, system)
    await _teams(engine, tenant, TEAM)
    flaky, fine = await connection(store, tenant, "team"), await connection(store, tenant, "person")
    await _held(engine, tokens, tenant, flaky, "rt-flaky", idle=IDLE + timedelta(days=1))
    await _held(engine, tokens, tenant, fine, "rt-fine", idle=IDLE)
    assert await keepalive.once() == 1
    assert system.refreshed == ["rt-fine"], system.refreshed
    account = await store.get(tenant, flaky)
    assert account is not None and account["status"] == "healthy", account
    held = await store.token(tenant, flaky)
    assert held is not None and held["refused_at"] is None, held


async def test_every_teams_sign_ins_are_kept_in_their_own_team(engine: AsyncEngine, tenant: str) -> None:
    system = System()
    store, tokens, keepalive = rig(engine, system)
    await _teams(engine, tenant, TEAM, OTHER)
    ours = await connection(store, tenant, "team")
    theirs = "con_cards"
    # Another team's account, a copy of ours in that team.
    async with engine.begin() as c:
        await c.execute(
            sa.text(
                "INSERT INTO connections (tenant_id, id, team_id, name, auth_kind, status, app_id, settings, secrets, "
                "revision, sign_in, team_backup, sandbox, created_by, created_at, updated_by, updated_at) "
                "SELECT tenant_id, :id, :team, name, auth_kind, status, :id, settings, secrets, revision, sign_in, "
                "team_backup, sandbox, created_by, created_at, updated_by, updated_at FROM connections "
                "WHERE tenant_id = :tenant AND id = :ours"
            ),
            {"id": theirs, "team": OTHER, "tenant": tenant, "ours": ours},
        )
    await _held(engine, tokens, tenant, ours, "rt-ours", idle=IDLE)
    await _held(engine, tokens, tenant, theirs, "rt-theirs", idle=IDLE)
    assert await keepalive.once() == 2
    assert sorted(system.refreshed) == ["rt-ours", "rt-theirs"], system.refreshed
