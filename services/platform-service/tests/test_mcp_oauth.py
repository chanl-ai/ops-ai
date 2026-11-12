"""platform-service as the authorization server for a team's MCP address, by failure mode: a client that cannot find
where to sign in, abuse of open registration, a code replayed or swapped, a token tied to nothing, a stolen renewal, a
person who left the team, a connection that never ends, and a lookalike client.

Paths: /.well-known/oauth-authorization-server, POST /oauth/register, GET /oauth/authorize, POST /oauth/token, and
the person's own side of the browser step as JSON, GET and POST /v1/oauth/consent (what the console's consent
page calls with the person's sign-in), GET /v1/oauth/grants. The MCP address of a team is
<tools-service public URL>/mcp/<team>, on another base than this service's own."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import sqlalchemy as sa

from ops_platform.api.app import create_public_app
from ops_platform.keys import dev_signer
from ops_platform.signin_options import SignInOptions
from ops_platform.store.identity import IdentityStore
from ops_platform.store.roles import mirror_membership
from ops_platform.store.tables import audit_entries, members, role_assignments, sessions, users
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, MCP_URL, PUBLIC_URL, SignInRig

REDIRECT = "https://claude.example/callback"
REGISTRATION = {"client_name": "Claude", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"}


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def claims_of(token: str) -> dict[str, Any]:
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def audiences(claims: dict[str, Any]) -> list[str]:
    aud = claims["aud"]
    return [aud] if isinstance(aud, str) else list(aud)


class Assistant:
    """A scripted OAuth client such as Claude or Cursor, and the person who signs in for it."""

    def __init__(self, rig: SignInRig) -> None:
        self.rig = rig
        self.api: httpx.AsyncClient = rig.public
        self.verifier = secrets.token_urlsafe(48)

    async def register(self, *, name: str = "Claude", redirect: str = REDIRECT) -> httpx.Response:
        return await self.api.post(
            "/oauth/register",
            json={
                "client_name": name,
                "redirect_uris": [redirect],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )

    async def client(self, **kw: str) -> str:
        r = await self.register(**kw)
        assert r.status_code == 201, r.text
        return r.json()["client_id"]

    def params(self, client_id: str, team: str, **over: str) -> dict[str, str]:
        return {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge_of(self.verifier),
            "code_challenge_method": "S256",
            "resource": f"{MCP_URL}/mcp/{team}",
            "state": "st-1",
            **over,
        }

    async def person(self, role: str = "builder") -> tuple[dict[str, str], str]:
        """A password sign-in of a new person who is a member of a team of their own: the console's headers and the
        team's id."""
        email = f"{new_id('usr')}@bank.test"
        user = await self.rig.person(email, role=role)
        async with self.rig.engine.connect() as c:
            team = (await c.execute(sa.select(members.c.team_id).where(members.c.user_id == user))).scalar_one()
        r = await self.api.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
        return {"Authorization": f"Bearer {r.json()['data']['token']}"}, team

    async def allow(self, who: dict[str, str], params: dict[str, str]) -> httpx.Response:
        """The person presses Allow on the consent page."""
        body = {k: v for k, v in params.items() if k != "response_type"}
        return await self.api.post("/v1/oauth/consent", json={**body, "decision": "allow"}, headers=who)

    async def code(self, who: dict[str, str], params: dict[str, str]) -> str:
        r = await self.allow(who, params)
        assert r.status_code == 200, r.text
        redirect: str = r.json()["data"]["redirectTo"]
        query = parse_qs(urlsplit(redirect).query)
        assert query["state"] == [params["state"]]
        return query["code"][0]

    async def exchange(self, code: str, params: dict[str, str], **over: str) -> httpx.Response:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": params["client_id"],
            "redirect_uri": params["redirect_uri"],
            "code_verifier": self.verifier,
            "resource": params["resource"],
            **over,
        }
        return await self.api.post("/oauth/token", data=form)

    async def connect(self, who: dict[str, str], params: dict[str, str]) -> dict[str, Any]:
        r = await self.exchange(await self.code(who, params), params)
        assert r.status_code == 200, r.text
        return r.json()

    async def renew(self, refresh_token: str, client_id: str) -> httpx.Response:
        return await self.api.post(
            "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
        )


# uc-mcp-1
async def test_the_server_metadata_tells_a_client_how_to_register_and_which_challenge_to_use(signin: SignInRig) -> None:
    r = await signin.public.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["issuer"] == PUBLIC_URL
    assert meta["code_challenge_methods_supported"] == ["S256"]
    # URL client ids are refused until the public-address check ships; the server must not advertise what it refuses.
    assert meta["client_id_metadata_document_supported"] is False
    assert meta["registration_endpoint"].startswith(PUBLIC_URL)
    assert meta["token_endpoint"].startswith(PUBLIC_URL) and meta["authorization_endpoint"].startswith(PUBLIC_URL)


# uc-mcp-7
async def test_registration_refuses_redirects_anyone_could_use_and_allows_10_a_minute_per_source_address(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    for bad in ("http://claude.example/callback", "javascript:alert(1)", "https://claude.example/cb#frag"):
        r = await a.register(redirect=bad)
        assert r.status_code == 400, (bad, r.status_code, r.text)
    for ok in ("http://127.0.0.1:33418/callback", "cursor://anysphere.cursor-mcp/oauth/callback"):
        assert (await a.register(redirect=ok)).status_code == 201, ok
    # A source address of this test's own, so the other tests' registrations do not count against it.
    transport = httpx.ASGITransport(app=signin.app, client=("203.0.113.7", 40000))
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as other:
        a.api = other
        statuses = [(await a.register()).status_code for _ in range(10)]
        assert statuses == [201] * 10, statuses
        eleventh = await a.register()
    assert eleventh.status_code == 429 and 0 < int(eleventh.headers["retry-after"]) <= 60, eleventh.text


# uc-mcp-1
async def test_an_install_with_no_public_address_answers_503_for_its_metadata_and_a_sign_in_start(
    database_url: str,
) -> None:
    store = IdentityStore.open(database_url)
    bare = SignInOptions(password_iterations=1_000, password_min_length=12, flow_ttl_s=600, reset_ttl_s=3600)
    app = create_public_app(store, dev_signer(), demo_password=None, audiences=["platform"], signin=bare)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_URL) as api:
        meta = await api.get("/.well-known/oauth-authorization-server")
        start = await api.get("/oauth/authorize", params={"response_type": "code"}, follow_redirects=False)
    assert (meta.status_code, meta.json()["error"]) == (503, "server_error"), meta.text
    assert "OPS_PLATFORM_PUBLIC_URL" in meta.json()["error_description"]
    assert start.status_code == 503 and "location" not in start.headers, start.text


# uc-mcp-7
async def test_sign_in_starts_are_limited_to_30_a_minute_per_source_address(signin: SignInRig) -> None:
    transport = httpx.ASGITransport(app=signin.app, client=("203.0.113.8", 40000))
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as other:
        statuses = [
            (await other.get("/oauth/authorize", params={"response_type": "code"})).status_code for _ in range(30)
        ]
        last = await other.get("/oauth/authorize", params={"response_type": "code"})
    assert 429 not in statuses, statuses
    assert last.status_code == 429 and 0 < int(last.headers["retry-after"]) <= 60, last.text


# uc-mcp-7
async def test_callers_behind_the_proxy_are_counted_apart_and_every_replica_sees_the_same_count(
    signin: SignInRig, database_url: str
) -> None:
    """Behind Caddy every request's peer is the proxy (127.0.0.1, trusted): the caller is read from X-Forwarded-For,
    and the count is the database's, so a second platform-service replica refuses the same caller."""
    caller_a = {"X-Forwarded-For": "203.0.113.21"}
    a_statuses = [
        (await signin.public.post("/oauth/register", json=REGISTRATION, headers=caller_a)).status_code
        for _ in range(10)
    ]
    assert a_statuses == [201] * 10, a_statuses
    eleventh = await signin.public.post("/oauth/register", json=REGISTRATION, headers=caller_a)
    assert eleventh.status_code == 429, eleventh.text
    # A left-hand entry the caller wrote itself does not make it someone else.
    spoofed = {"X-Forwarded-For": "198.51.100.5, 203.0.113.21"}
    assert (await signin.public.post("/oauth/register", json=REGISTRATION, headers=spoofed)).status_code == 429
    caller_b = {"X-Forwarded-For": "203.0.113.22"}
    assert (await signin.public.post("/oauth/register", json=REGISTRATION, headers=caller_b)).status_code == 201
    store = IdentityStore.open(database_url)
    replica = create_public_app(
        store, dev_signer(), demo_password=None, audiences=["platform"],
        signin=SignInOptions(password_iterations=1_000, password_min_length=12, flow_ttl_s=600, reset_ttl_s=3600),
    )  # fmt: skip
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=replica), base_url=PUBLIC_URL) as other:
        again = await other.post("/oauth/register", json=REGISTRATION, headers=caller_a)
    await store.close()
    assert again.status_code == 429, again.text


# uc-mcp-7
async def test_a_client_never_consented_to_is_pruned_after_24_hours_and_a_consented_one_is_kept(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    idle, used = await a.client(name="Idle"), await a.client(name="Used")
    who, team = await a.person()
    await a.connect(who, a.params(used, team))
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    async with signin.engine.begin() as c:
        await c.execute(
            sa.text("UPDATE oauth_clients SET created_at = :t WHERE id IN (:a, :b)"), {"t": old, "a": idle, "b": used}
        )
    await a.client(name="Trigger")  # a registration runs the prune
    gone = await signin.public.get("/oauth/authorize", params=a.params(idle, team), follow_redirects=False)
    kept = await signin.public.get("/oauth/authorize", params=a.params(used, team), follow_redirects=False)
    assert gone.status_code == 400 and "location" not in gone.headers
    assert kept.status_code in (302, 303), kept.status_code


# uc-mcp-6, uc-mcp-15
async def test_authorize_refuses_a_missing_or_plain_challenge_and_never_redirects_to_an_unregistered_address(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    team = signin.ops_team
    ok = a.params(client, team)
    for label, params in {
        "no challenge": {k: v for k, v in ok.items() if k != "code_challenge"},
        "plain": {**ok, "code_challenge_method": "plain"},
        "resource of no team here": {**ok, "resource": f"{MCP_URL}/mcp/{new_id('team')}"},
        "resource on this service's own base": {**ok, "resource": f"{PUBLIC_URL}/mcp/{team}"},
        "resource on another host": {**ok, "resource": f"https://evil.example/mcp/{team}"},
    }.items():
        r = await signin.public.get("/oauth/authorize", params=params, follow_redirects=False)
        assert r.status_code == 400, (label, r.status_code, r.text)
        assert "location" not in r.headers, label
    # An address the client did not register: an error page, never a redirect carrying anything to it.
    r = await signin.public.get(
        "/oauth/authorize", params={**ok, "redirect_uri": "https://evil.example/callback"}, follow_redirects=False
    )
    assert r.status_code == 400 and "location" not in r.headers
    who, _ = await a.person()
    r = await a.allow(who, {**ok, "redirect_uri": "https://evil.example/callback"})
    assert r.status_code == 400 and "code" not in r.text


# uc-mcp-15, uc-mcp-16
async def test_the_consent_names_the_host_the_browser_returns_to_marks_the_name_self_reported_and_needs_the_team(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client(name="Official Microsoft Copilot")
    who, team = await a.person()
    params = a.params(client, team)
    shown = await signin.public.get("/v1/oauth/consent", params=params, headers=who)
    assert shown.status_code == 200, shown.text
    data = shown.json()["data"]
    assert data["redirectHost"] == "claude.example"
    assert data["client"]["name"] == "Official Microsoft Copilot"
    assert data["client"]["nameIsSelfReported"] is True
    assert data["team"]["id"] == team
    assert "teams" not in data, "the address names the team; there is no picker"
    # A person who is not in the address's team is told so and given no code.
    outsider, _ = await a.person()
    refused = await a.allow(outsider, params)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "team_forbidden", refused.text
    assert "code=" not in refused.text


# uc-mcp-6
async def test_a_code_used_twice_revokes_what_it_issued_and_a_code_is_bound_to_its_verifier_redirect_and_resource(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    who, team = await a.person()
    params = a.params(client, team)
    first = await a.exchange(await a.code(who, params), params)
    assert first.status_code == 200, first.text
    code = await a.code(who, params)
    assert (await a.exchange(code, params, code_verifier="x" * 50)).status_code == 400
    assert (await a.exchange(code, params, redirect_uri="https://claude.example/other")).status_code == 400
    r = await a.exchange(code, params, resource=f"{MCP_URL}/mcp/{new_id('team')}")
    assert r.json()["error"] == "invalid_target", r.text
    fresh = await a.code(who, params)
    used = await a.exchange(fresh, params)
    assert used.status_code == 200
    again = await a.exchange(fresh, params)
    assert (again.status_code, again.json()["error"]) == (400, "invalid_grant")
    renewed = await a.renew(used.json()["refresh_token"], client)
    assert renewed.status_code == 400, "the replay revoked the grant the code had issued"


# uc-mcp-2, uc-mcp-3
async def test_the_token_is_for_the_one_address_and_team_for_15_minutes_and_no_rest_route_takes_it(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    who, team = await a.person()
    params = a.params(client, team)
    got = await a.connect(who, params)
    claims = claims_of(got["access_token"])
    assert audiences(claims) == [params["resource"]], "the address and nothing else, no service names"
    assert claims["team_ids"] == [team]
    assert got["expires_in"] == 900 and claims["exp"] - claims["iat"] == 900
    r = await signin.public.get("/v1/auth/session", headers={"Authorization": f"Bearer {got['access_token']}"})
    assert r.status_code == 401
    r = await signin.public.get("/v1/me/permissions", headers={"Authorization": f"Bearer {got['access_token']}"})
    assert r.status_code == 401


# uc-mcp-4
async def test_a_renewal_used_twice_ends_the_grant_and_no_renewal_works_at_the_other_endpoint(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    other = await a.client(name="Cursor")
    who, team = await a.person()
    got = await a.connect(who, a.params(client, team))
    # Another client presenting it, and each kind of renewal at the other endpoint.
    wrong = await a.renew(got["refresh_token"], other)
    assert (wrong.status_code, wrong.json()["error"]) == (400, "invalid_grant")
    at_console = await signin.public.post("/v1/auth/refresh", json={"refreshToken": got["refresh_token"]})
    assert at_console.status_code == 401
    email = f"{new_id('usr')}@bank.test"
    await signin.person(email)
    console = (await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})).json()
    refused = await a.renew(console["data"]["refreshToken"], client)
    assert (refused.status_code, refused.json()["error"]) == (400, "invalid_grant")
    # Reuse: the first renewal works once; the old one then ends the whole grant, new one included.
    first = await a.renew(got["refresh_token"], client)
    assert first.status_code == 200, first.text
    reused = await a.renew(got["refresh_token"], client)
    assert (reused.status_code, reused.json()["error"]) == (400, "invalid_grant")
    assert (await a.renew(first.json()["refresh_token"], client)).status_code == 400
    async with signin.engine.connect() as c:
        actions = (await c.execute(sa.select(audit_entries.c.action).where(audit_entries.c.team_id == team))).scalars()
        assert "auth.refresh_reuse" in list(actions)


# uc-mcp-5
async def test_a_person_removed_from_the_team_or_who_disconnects_cannot_renew_and_each_end_is_audited(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    who, team = await a.person()
    got = await a.connect(who, a.params(client, team))
    async with signin.engine.begin() as c:
        found = sa.select(members.c.id, members.c.user_id, members.c.email).where(members.c.team_id == team)
        member, user, email = (await c.execute(found)).one()
        # The person stays in another team, so leaving this one is the only thing the renewal can refuse on.
        now = now_iso()
        await c.execute(
            members.insert().values(
                id=new_id("mem"), tenant_id=signin.tenant, team_id=signin.ops_team, user_id=user, email=email,
                role="viewer", status="active", created_at=now, updated_at=now,
            )
        )  # fmt: skip
    # Signed in after the team exists: a token carries the teams it was minted with, so the rig's admin token
    # (minted before this team) would be refused with team_forbidden whatever the renewal does.
    async with signin.engine.connect() as c:
        admin_email = (
            await c.execute(sa.select(users.c.email).where(users.c.tenant_id == signin.tenant, users.c.name == "Sam"))
        ).scalar_one()
    login = await signin.public.post("/v1/auth/sign-in", json={"email": admin_email, "password": DEMO_PASSWORD})
    admin = {"Authorization": f"Bearer {login.json()['data']['token']}", "X-Team-Id": team}
    removed = await signin.public.post("/v1/settings/members/delete", json={"ids": [member]}, headers=admin)
    assert removed.status_code == 200, removed.text
    # Removal already ends the person's sessions. Reopen this grant so the renewal's own team check is the only thing
    # left that can refuse it.
    async with signin.engine.begin() as c:
        await c.execute(sessions.update().where(sessions.c.user_id == user).values(revoked_at=None))
    renewed = await a.renew(got["refresh_token"], client)
    assert (renewed.status_code, renewed.json()["error"]) == (400, "invalid_grant"), "never a token with fewer teams"
    # Disconnect by the person, on a second connection of the same person.
    mine = await a.client(name="Cursor")
    who2, team2 = await a.person()
    second = await a.connect(who2, a.params(mine, team2))
    grants = (await signin.public.get("/v1/oauth/grants", headers=who2)).json()["data"]
    assert (await signin.public.delete(f"/v1/oauth/grants/{grants[0]['id']}", headers=who2)).status_code == 204
    assert (await a.renew(second["refresh_token"], mine)).status_code == 400
    async with signin.engine.connect() as c:
        rows = (
            (await c.execute(sa.select(audit_entries).where(audit_entries.c.tenant_id == signin.tenant)))
            .mappings()
            .all()
        )
    by_action = {(r["action"], r["team_id"]): r for r in rows}
    assert ("oauth.grant_allowed", team) in by_action and ("oauth.grant_allowed", team2) in by_action
    assert by_action[("oauth.grant_ended", team)]["detail"]["by"] == "admin"
    assert by_action[("oauth.grant_ended", team2)]["detail"]["by"] == "person"
    # The registration row had no tenant; the first consent adds the tenant and team.
    assert by_action[("oauth.client_registered", team2)]["target_id"] == mine


# uc-mcp-5
# uc-mcp-5
async def test_a_person_who_stays_in_the_team_but_loses_the_right_to_run_its_tools_cannot_renew(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    who, team = await a.person()
    got = await a.connect(who, a.params(client, team))
    # Still a member of the address's team, now as a viewer, who may not run its tools. Set in the tables (the
    # membership and the role assignment the member routes keep equal to it) so nothing else, such as a role change
    # ending sessions, can be what refuses the renewal.
    async with signin.engine.begin() as c:
        await c.execute(members.update().where(members.c.team_id == team).values(role="viewer"))
        await c.execute(role_assignments.update().where(role_assignments.c.team_id == team).values(role_id="viewer"))
    renewed = await a.renew(got["refresh_token"], client)
    assert (renewed.status_code, renewed.json()["error"]) == (400, "invalid_grant"), renewed.text
    # The grant ended with it: a second renewal is refused too, and the person's list no longer shows it.
    assert (await a.renew(got["refresh_token"], client)).status_code == 400
    assert (await signin.public.get("/v1/oauth/grants", headers=who)).json()["data"] == []


# uc-mcp-17
async def test_leaving_the_workspace_or_a_password_reset_audits_each_assistant_connection_it_ends(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    leaver, team = await a.person()
    await a.connect(leaver, a.params(client, team))
    assert (await signin.public.post("/v1/workspace/leave", headers=leaver)).status_code == 204
    resetter, team2 = await a.person()
    await a.connect(resetter, a.params(client, team2))
    async with signin.engine.connect() as c:
        email = (await c.execute(sa.select(members.c.email).where(members.c.team_id == team2))).scalar_one()
    assert (await signin.public.post("/v1/auth/password/forgot", json={"email": email})).status_code == 204
    [mail] = [m for m in signin.mail.sent.values() if m.to == (email,)]
    found = re.search(r"/reset-password/(prt_[A-Za-z0-9_-]+)", mail.body)
    assert found, mail.body
    reset = await signin.public.post(
        "/v1/auth/password/reset", json={"token": found.group(1), "password": "a new password 12"}
    )
    assert reset.status_code in (200, 204), reset.text
    async with signin.engine.connect() as c:
        q = sa.select(audit_entries.c.team_id, audit_entries.c.detail).where(
            audit_entries.c.tenant_id == signin.tenant, audit_entries.c.action == "oauth.grant_ended"
        )
        ended = {(str(t), d["by"]) for t, d in (await c.execute(q)).all()}
    assert {(team, "person"), (team2, "password_reset")} <= ended, ended


async def test_a_connection_lasts_the_workspace_setting_8_hours_unless_an_admin_changes_it(signin: SignInRig) -> None:
    a = Assistant(signin)
    client = await a.client()
    who, team = await a.person()

    async def hours_left() -> float:
        await a.connect(who, a.params(client, team))
        grants = (await signin.public.get("/v1/oauth/grants", headers=who)).json()["data"]
        newest = max(grants, key=lambda g: g["createdAt"])
        assert newest["lastUsedAt"] is None, "a connection that has not renewed has no last use"
        left = datetime.fromisoformat(newest["expiresAt"]) - datetime.now(UTC)
        return left.total_seconds() / 3600

    assert 7.9 < await hours_left() <= 8.0
    put = await signin.public.put("/v1/policies/mcpConnectionHours", json={"value": 2}, headers=signin.admin)
    assert put.status_code == 200, put.text
    assert 1.9 < await hours_left() <= 2.0
    too_long = await signin.public.put("/v1/policies/mcpConnectionHours", json={"value": 31 * 24}, headers=signin.admin)
    assert too_long.status_code == 422, "at most 30 days"


async def _admin_for(signin: SignInRig, team: str) -> tuple[dict[str, str], str]:
    """The rig's admin signed in after `team` exists (a token carries the teams it was minted with), and their id."""
    async with signin.engine.connect() as c:
        email, admin = (
            await c.execute(
                sa.select(users.c.email, users.c.id).where(users.c.tenant_id == signin.tenant, users.c.name == "Sam")
            )
        ).one()
    login = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {login.json()['data']['token']}", "X-Team-Id": team}, str(admin)


# uc-mcp-17
async def test_removing_a_person_from_the_team_audits_the_assistant_connection_it_ends_without_a_renewal(
    signin: SignInRig,
) -> None:
    a = Assistant(signin)
    client = await a.client()
    who, team = await a.person()
    await a.connect(who, a.params(client, team))
    [grant] = (await signin.public.get("/v1/oauth/grants", headers=who)).json()["data"]
    admin, admin_id = await _admin_for(signin, team)
    async with signin.engine.connect() as c:
        member = (await c.execute(sa.select(members.c.id).where(members.c.team_id == team))).scalar_one()
    removed = await signin.public.post("/v1/settings/members/delete", json={"ids": [member]}, headers=admin)
    assert removed.status_code == 200, removed.text
    # No renewal is tried: the removal itself writes the row.
    async with signin.engine.connect() as c:
        q = sa.select(audit_entries).where(
            audit_entries.c.action == "oauth.grant_ended", audit_entries.c.team_id == team
        )
        rows = (await c.execute(q)).mappings().all()
    assert [(r["target_id"], r["actor"], r["detail"]["by"]) for r in rows] == [(grant["id"], admin_id, "admin")], rows


# uc-mcp-2
async def test_a_person_in_two_teams_gets_a_token_for_the_addresses_team_only(signin: SignInRig) -> None:
    a = Assistant(signin)
    client = await a.client()
    _, team = await a.person()
    # Also a builder in the rig's ops team, so the person's own sign-in names two teams.
    async with signin.engine.begin() as c:
        user, email = (
            await c.execute(sa.select(members.c.user_id, members.c.email).where(members.c.team_id == team))
        ).one()
        now = now_iso()
        await c.execute(
            members.insert().values(
                id=new_id("mem"), tenant_id=signin.tenant, team_id=signin.ops_team, user_id=user, email=email,
                role="builder", status="active", created_at=now, updated_at=now,
            )
        )  # fmt: skip
        await mirror_membership(
            c, tenant_id=signin.tenant, team_id=signin.ops_team, user_id=user, member_role="builder",
            security_team=signin.security_team, granted_by="test", at=now,
        )  # fmt: skip
    login = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    console = claims_of(login.json()["data"]["token"])
    assert {team, signin.ops_team} <= set(console["team_ids"]), console["team_ids"]
    assert {team, signin.ops_team} <= set(console["roles"]), console["roles"]
    got = await a.connect({"Authorization": f"Bearer {login.json()['data']['token']}"}, a.params(client, team))
    claims = claims_of(got["access_token"])
    assert claims["team_ids"] == [team]
    assert set(claims["roles"]) == {team}, claims["roles"]
    assert set(claims["access"]) <= {team, "*"}, claims["access"]
    renewed = await a.renew(got["refresh_token"], client)
    assert renewed.status_code == 200, renewed.text
    assert claims_of(renewed.json()["access_token"])["team_ids"] == [team]
