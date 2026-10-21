"""Widget deployments and the widget API (c-117), by failure mode: an embed that follows a newer agent version instead
of its pin; a session minted for, or used from, an origin the deployment does not list; a server outside the team, or
a person's token, minting server sessions; a page changing what only trusted callers may; no limit on a busy page; a
browser on another page reading a widget response; a paused widget still answering; someone other than a builder
making deployments; a team key, a person's token, a revoked key or another deployment's key minting server sessions
(c-131); a paused agent still answering an open widget conversation; a person of another team, or a key,
minting from the page; an error the page cannot read; a session naming another tenant or team, another deployment, or
past its expiry."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, tzinfo
from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_agents.api import widget_sessions
from ops_agents.api.routers import widget as widget_routes
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import HmacSigner, mint
from ops_service_kit.settings import Settings
from tests.api import test_write_approval_policy as platform_stub
from tests.api.test_write_approval_policy import PLATFORM, _client  # pyright: ignore[reportPrivateUsage]
from tests.conftest import SEED, sse_events

INTRANET = "https://intranet.bank.example"
PORTAL = "https://portal.bank.example"
LOOKUP = "Look up CHQ-2219"
# The embed app's origin: the test client's own host, as a deployment serves apps/embed beside /v1.
EMBED = "http://test"
SETTINGS = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, embed_origins=[EMBED])


def who(sub: str, role: str, team: str = "team_ops") -> dict[str, str]:
    claims = {
        "sub": sub,
        "email": f"{sub}@harborpine.example",
        "name": sub,
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": "acme",
        "team_ids": [team],
        "roles": {team: role},
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


BUILDER, VIEWER, BANKER, OUTSIDER = (
    who("usr_b", "builder"),
    who("usr_v", "viewer"),
    who("usr_k", "viewer"),
    who("usr_o", "builder", "team_fraud"),
)


# Team API keys as platform-service introspection answers them: one per team.
KEYS = {"ok_ops.k1": "team_ops", "ok_fraud.k2": "team_fraud"}
OPS_KEY, FRAUD_KEY = {"X-API-Key": "ok_ops.k1"}, {"X-API-Key": "ok_fraud.k2"}


async def introspect(key: str) -> dict[str, Any] | None:
    team = KEYS.get(key)
    if team is None:
        return None
    return {
        "sub": f"key_{team}",
        "name": "bank server",
        "tenantId": "acme",
        "teamId": team,
        "scopes": ["read", "write"],
    }


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(platform_stub, "introspect", introspect)
    async for c in _client(SETTINGS, platform=True):
        yield c


async def deploy(client: AsyncClient, origins: list[str] | None = None) -> dict[str, Any]:
    res = await client.post(
        "/v1/widget-deployments",
        json={"name": "Intranet help", "agentId": "ag_fraud", "origins": origins or [INTRANET]},
        headers=BUILDER,
    )
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def session(client: AsyncClient, dep: str, origin: str = INTRANET) -> str:
    res = await client.post(f"/v1/widget/{dep}/session", headers={**BANKER, "Origin": origin})
    assert res.status_code == 201, res.text
    return res.json()["data"]["session"]


def page(token: str, origin: str = INTRANET) -> dict[str, str]:
    return {"X-Widget-Session": token, "Origin": origin}


async def thread(client: AsyncClient, dep: str, token: str) -> str:
    res = await client.post(f"/v1/widget/{dep}/threads", headers=page(token))
    assert res.status_code == 201, res.text
    return res.json()["data"]["id"]


async def tool_calls(client: AsyncClient, dep: str, token: str, tid: str) -> list[str]:
    res = await client.get(f"/v1/widget/{dep}/threads/{tid}", headers=page(token))
    messages: list[dict[str, Any]] = res.json()["data"]["messages"]
    return [str(c["name"]) for m in messages for c in cast(list[dict[str, Any]], m.get("toolCalls") or [])]


async def test_only_a_builder_of_the_team_makes_deployments(client: AsyncClient) -> None:
    refused = await client.post(
        "/v1/widget-deployments", json={"name": "x", "agentId": "ag_fraud", "origins": [INTRANET]}, headers=VIEWER
    )
    wildcard = await client.post(
        "/v1/widget-deployments",
        json={"name": "x", "agentId": "ag_fraud", "origins": ["https://*.bank.example"]},
        headers=BUILDER,
    )
    assert refused.status_code == 403 and wildcard.status_code == 400


async def test_an_embed_keeps_serving_its_pinned_version_after_a_newer_one_goes_live(client: AsyncClient) -> None:
    dep = await deploy(client)
    token = await session(client, dep["id"])
    agent = (await client.get("/v1/agents/ag_fraud", headers=BUILDER)).json()["data"]
    saved = await client.patch("/v1/agents/ag_fraud", json={"toolIds": [], "note": "no lookups"}, headers=BUILDER)
    assert saved.status_code == 200, saved.text
    published = await client.post(
        "/v1/agents/ag_fraud/publish-requests",
        json={"version": saved.json()["data"]["version"], "note": "v2"},
        headers=BUILDER,
    )
    assert published.status_code in (200, 201), published.text
    assert (await client.get("/v1/agents/ag_fraud", headers=BUILDER)).json()["data"]["publishedVersion"] > agent[
        "publishedVersion"
    ]
    tid = await thread(client, dep["id"], token)
    sent = await client.post(
        f"/v1/widget/{dep['id']}/threads/{tid}/messages",
        json={"content": LOOKUP},
        headers={**page(token), "Accept": "text/event-stream"},
    )
    assert sent.status_code == 200, sent.text
    assert await tool_calls(client, dep["id"], token, tid) == ["lookup_account"], (
        "the widget still serves the pinned version"
    )
    latest = {"serves": {"kind": "agent", "id": dep["agentId"], "version": "latest"}}
    moved = (await client.patch(f"/v1/channels/{dep['id']}", json=latest, headers=BUILDER)).json()["data"]["serves"]
    assert moved["version"] == "latest" and moved["latestVersion"] > dep["agentVersion"], moved


async def test_a_session_needs_an_allowed_origin_and_stays_on_it(client: AsyncClient) -> None:
    dep = await deploy(client, [INTRANET, PORTAL])
    other = await client.post(f"/v1/widget/{dep['id']}/session", headers={**BANKER, "Origin": "https://evil.example"})
    no_origin = await client.post(f"/v1/widget/{dep['id']}/session", headers=BANKER)
    token = await session(client, dep["id"])
    moved = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token, PORTAL))
    missing = await client.post(f"/v1/widget/{dep['id']}/threads", headers={"Origin": INTRANET})
    forged = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token[:-4] + "AAAA"))
    assert other.status_code == 403 and no_origin.status_code == 403
    assert moved.status_code == 403 and moved.json()["error"]["code"] == "origin_mismatch"
    assert missing.status_code == 401 and forged.status_code == 401


async def mint_key(client: AsyncClient, dep: str) -> str:
    res = await client.post(f"/v1/widget-deployments/{dep}/keys", json={"name": "Intranet server"}, headers=BUILDER)
    assert res.status_code == 201, res.text
    return str(res.json()["data"]["secret"])


async def test_only_the_deployments_mint_key_mints_server_sessions(client: AsyncClient) -> None:
    dep, other = await deploy(client), await deploy(client)
    body = {"email": "banker@bank.example", "name": "Banker", "origin": INTRANET}
    url = f"/v1/widget-deployments/{dep['id']}/sessions"
    key = await mint_key(client, dep["id"])
    minted = await client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    assert minted.status_code == 201, minted.text
    tid = await thread(client, dep["id"], minted.json()["data"]["session"])
    assert tid.startswith("th_")
    listed = (await client.get(f"/v1/widget-deployments/{dep['id']}/keys", headers=BUILDER)).json()["data"]
    assert listed[0]["lastUsedAt"], "a mint is recorded on its key"
    # A team API key minted sessions before c-131; it can call far more than one chat, so it no longer may.
    team_key = await client.post(url, json=body, headers=OPS_KEY)
    assert team_key.status_code == 403 and team_key.json()["error"]["code"] == "widget_key_required", team_key.text
    elsewhere = await client.post(
        f"/v1/widget-deployments/{other['id']}/sessions", json=body, headers={"Authorization": f"Bearer {key}"}
    )
    assert elsewhere.status_code == 403 and elsewhere.json()["error"]["code"] == "widget_key_other_deployment"
    forged = await client.post(url, json=body, headers={"Authorization": f"Bearer {key[:-4]}xxxx"})
    assert forged.status_code == 401


async def test_a_revoked_mint_key_mints_nothing_and_the_secret_is_never_listed(client: AsyncClient) -> None:
    dep = await deploy(client)
    key = await mint_key(client, dep["id"])
    listed = (await client.get(f"/v1/widget-deployments/{dep['id']}/keys", headers=BUILDER)).json()["data"]
    assert len(listed) == 1 and key.split(".")[-1] not in str(listed)
    revoked = await client.post(f"/v1/widget-deployments/{dep['id']}/keys/{listed[0]['id']}/revoke", headers=BUILDER)
    assert revoked.status_code == 200, revoked.text
    body = {"email": "banker@bank.example", "name": "Banker", "origin": INTRANET}
    after = await client.post(
        f"/v1/widget-deployments/{dep['id']}/sessions", json=body, headers={"Authorization": f"Bearer {key}"}
    )
    assert after.status_code == 401 and after.json()["error"]["code"] == "widget_key_invalid"
    viewer = await client.post(f"/v1/widget-deployments/{dep['id']}/keys", json={"name": "x"}, headers=VIEWER)
    assert viewer.status_code in (403, 404), viewer.text


async def test_a_persons_token_never_mints_a_server_session(client: AsyncClient) -> None:
    dep = await deploy(client)
    url = f"/v1/widget-deployments/{dep['id']}/sessions"
    viewer = await client.post(
        url, json={"email": "usr_v@harborpine.example", "name": "V", "origin": INTRANET}, headers=VIEWER
    )
    other = await client.post(
        url, json={"email": "ceo@harborpine.example", "name": "CEO", "origin": INTRANET}, headers=BUILDER
    )
    assert viewer.status_code == 403 and viewer.json()["error"]["code"] == "widget_key_required"
    assert other.status_code == 403 and other.json()["error"]["code"] == "widget_key_required"


async def test_a_page_may_change_only_what_a_public_key_may(client: AsyncClient) -> None:
    dep = await deploy(client)
    token = await session(client, dep["id"])
    tid = await thread(client, dep["id"], token)
    refused = await client.post(
        f"/v1/widget/{dep['id']}/threads/{tid}/messages",
        json={"content": LOOKUP, "overrides": {"temperature": 0.5}},
        headers=page(token),
    )
    assert refused.status_code == 422 and refused.json()["error"]["details"]["field"] == "overrides.turn.temperature"


async def test_a_busy_page_is_rate_limited(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(widget_sessions, "PER_PERSON", 1)
    dep = await deploy(client)
    token = await session(client, dep["id"])
    tid = await thread(client, dep["id"], token)
    first = await client.post(
        f"/v1/widget/{dep['id']}/threads/{tid}/messages",
        json={"content": "hello"},
        headers={**page(token), "Accept": "text/event-stream"},
    )
    second = await client.post(
        f"/v1/widget/{dep['id']}/threads/{tid}/messages",
        json={"content": "again"},
        headers={**page(token), "Accept": "text/event-stream"},
    )
    assert (
        first.status_code == 200 and second.status_code == 429 and second.json()["error"]["details"]["retryAfter"] > 0
    )


async def test_only_the_deployments_origin_reads_a_widget_response(client: AsyncClient) -> None:
    dep = await deploy(client)
    token = await session(client, dep["id"])
    preflight = await client.options(
        f"/v1/widget/{dep['id']}/threads", headers={"Origin": INTRANET, "Access-Control-Request-Method": "POST"}
    )
    allowed = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token))
    refused = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token, "https://evil.example"))
    assert (
        preflight.status_code == 204 and "x-widget-session" in preflight.headers["access-control-allow-headers"].lower()
    )
    assert allowed.headers.get("access-control-allow-origin") == INTRANET
    assert refused.status_code == 403 and "access-control-allow-origin" not in refused.headers


async def test_a_paused_widget_answers_nothing(client: AsyncClient) -> None:
    dep = await deploy(client)
    token = await session(client, dep["id"])
    await client.patch(f"/v1/channels/{dep['id']}", json={"paused": True}, headers=BUILDER)
    blocked = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token))
    new_session = await client.post(f"/v1/widget/{dep['id']}/session", headers={**BANKER, "Origin": INTRANET})
    assert blocked.status_code == 409 and new_session.status_code == 409


async def test_pausing_the_agent_stops_its_open_widget_conversations(client: AsyncClient) -> None:
    dep = await deploy(client)
    token = await session(client, dep["id"])
    tid = await thread(client, dep["id"], token)
    paused = await client.post("/v1/agents/ag_fraud/paused", json={"paused": True}, headers=BUILDER)
    assert paused.status_code == 200, paused.text
    sent = await client.post(
        f"/v1/widget/{dep['id']}/threads/{tid}/messages",
        json={"content": "hello"},
        headers={**page(token), "Accept": "text/event-stream"},
    )
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "agent_paused", sent.text


async def test_only_a_person_of_the_deployments_team_signs_in_from_the_page(client: AsyncClient) -> None:
    dep = await deploy(client)
    url = f"/v1/widget/{dep['id']}/session"
    outsider = await client.post(url, headers={**who("usr_f", "approver", "team_fraud"), "Origin": INTRANET})
    key = await client.post(url, headers={**OPS_KEY, "Origin": INTRANET})
    assert outsider.status_code == 403 and outsider.json()["error"]["code"] == "team_forbidden"
    assert key.status_code == 403 and key.json()["error"]["code"] == "api_key_refused"


async def test_the_page_reads_an_error_on_its_listed_origin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dep = await deploy(client)
    monkeypatch.setattr(widget_sessions, "SESSION_TTL_S", -5)
    ended_token = await session(client, dep["id"])
    ended = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(ended_token))
    stranger = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(ended_token, "https://evil.example"))
    assert ended.status_code == 401 and ended.headers.get("access-control-allow-origin") == INTRANET
    assert stranger.status_code == 403 and "access-control-allow-origin" not in stranger.headers


async def test_a_session_is_refused_for_another_team_deployment_or_after_expiry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dep, other = await deploy(client), await deploy(client)
    signer = HmacSigner.derived(SETTINGS.review_key.get_secret_value(), "widget-session")
    claims = {"typ": widget_sessions.SESSION_TYPE, "dep": dep["id"], "origin": INTRANET, "email": "x@y.z", "name": "X"}
    forged = mint({**claims, "tenant": "acme", "team": "team_security", "sub": "x"}, signer, ttl_s=TEST_TOKEN_TTL_S)
    elsewhere = await session(client, other["id"])
    monkeypatch.setattr(widget_sessions, "SESSION_TTL_S", -5)
    expired = await session(client, dep["id"])
    for token in (forged, elsewhere, expired):
        res = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token))
        assert res.status_code == 401, (token[:12], res.text)


HOLD = 'call place_wire_hold {"wireId": "W-1", "hours": 24, "reason": "Unusual payee"}'


async def test_a_widget_hold_waits_for_human_tasks_and_the_page_has_no_route_to_decide_it(client: AsyncClient) -> None:
    dep = await deploy(client)
    key = {"Authorization": f"Bearer {await mint_key(client, dep['id'])}"}
    minted = await client.post(
        f"/v1/widget-deployments/{dep['id']}/sessions",
        json={"email": "asker@bank.example", "name": "Asker", "origin": INTRANET},
        headers=key,
    )
    asker = minted.json()["data"]["session"]
    tid = await thread(client, dep["id"], asker)
    sent = await client.post(
        f"/v1/widget/{dep['id']}/threads/{tid}/messages",
        json={"content": HOLD},
        headers={**page(asker), "Accept": "text/event-stream"},
    )
    assert [e for e in sse_events(sent.text) if e["type"] == "widget"], f"the hold stops: {sent.text[-400:]}"
    view = (await client.get(f"/v1/widget/{dep['id']}/threads/{tid}", headers=page(asker))).json()["data"]
    msg = next(m for m in view["messages"] if m.get("widgets"))
    # A widget session approves for no team, so the page has no decide route and no widget-action route.
    for path, body in (
        (f"/v1/widget/{dep['id']}/threads/{tid}/decision", {"decision": "approved"}),
        (f"/v1/widget/{dep['id']}/threads/{tid}/messages/{msg['id']}/widgets/{msg['widgets'][0]['id']}/actions", {}),
    ):
        refused = await client.post(path, json=body, headers=page(asker))
        assert refused.status_code in (404, 405), f"{path} {refused.status_code}"
    review = (await client.get(f"/reviews/{tid}", headers=BUILDER)).json()["data"]
    assert review["status"] == "pending", review


async def test_the_public_config_answers_a_listed_page_or_a_mint_key_and_names_no_team(client: AsyncClient) -> None:
    dep = await deploy(client, [INTRANET, PORTAL])
    url = f"/v1/widget/{dep['id']}/config"
    res = await client.get(url, params={"tenant": "acme"}, headers={"Origin": PORTAL})
    assert res.status_code == 200 and res.headers.get("access-control-allow-origin") == PORTAL, res.text
    data = res.json()["data"]
    assert set(data) == {"agentName", "deploymentName", "allowedOrigins", "paused", "retired", "suggestions"}, data
    assert sorted(data["allowedOrigins"]) == sorted([INTRANET, PORTAL]) and data["paused"] is False
    assert "team_ops" not in res.text and "acme" not in res.text
    key = {"Authorization": f"Bearer {await mint_key(client, dep['id'])}"}
    assert (await client.get(url, params={"tenant": "acme"}, headers=key)).status_code == 200
    # Nobody else reads it: no Origin and no key, an unlisted page, or another credential.
    for headers in ({}, {"Origin": "https://evil.example"}, OPS_KEY, {"Authorization": "Bearer ok_ops.k1"}):
        refused = await client.get(url, params={"tenant": "acme"}, headers=headers)
        assert refused.status_code in (401, 403) and "access-control-allow-origin" not in refused.headers, headers
    for params, dep_id in (({"tenant": "other"}, dep["id"]), ({"tenant": "acme"}, "wd_missing")):
        missing = await client.get(f"/v1/widget/{dep_id}/config", params=params, headers={"Origin": PORTAL})
        assert missing.status_code == 404, missing.text


async def test_a_mint_key_expires_and_its_create_and_revoke_are_audited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dep = await deploy(client)
    made = await client.post(
        f"/v1/widget-deployments/{dep['id']}/keys", json={"name": "Server", "expiresInDays": 1}, headers=BUILDER
    )
    assert made.status_code == 201 and made.json()["data"]["key"]["expiresAt"], made.text
    key, key_id = made.json()["data"]["secret"], made.json()["data"]["key"]["id"]
    body = {"email": "banker@bank.example", "name": "Banker", "origin": INTRANET}
    url = f"/v1/widget-deployments/{dep['id']}/sessions"
    assert (await client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})).status_code == 201

    class Later(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Later:
            return cast(Later, datetime.now(tz) + timedelta(days=2))

    monkeypatch.setattr(widget_routes, "datetime", Later)
    late = await client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    assert late.status_code == 401 and late.json()["error"]["code"] == "widget_key_expired", late.text
    monkeypatch.undo()
    too_long = {"name": "Server", "expiresInDays": 400}
    assert (
        await client.post(f"/v1/widget-deployments/{dep['id']}/keys", json=too_long, headers=BUILDER)
    ).status_code in (400, 422)
    await client.post(f"/v1/widget-deployments/{dep['id']}/keys/{key_id}/revoke", headers=BUILDER)
    audit = (await client.get(f"/v1/widget-deployments/{dep['id']}/keys/audit", headers=BUILDER)).json()["data"]
    assert [(r["keyId"], r["action"]) for r in audit] == [(key_id, "revoked"), (key_id, "created")], audit
    assert all(r["actor"] == "usr_b@harborpine.example" for r in audit), audit


async def test_the_loader_is_served_without_a_key(client: AsyncClient) -> None:
    res = await client.get("/embed/v1.js")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/javascript")
    assert "OpsChat" in res.text and "postMessage(msg, host)" in res.text, "the loader posts only to an exact origin"


async def test_the_first_widget_script_is_gone_rather_than_swapped_for_the_loader(client: AsyncClient) -> None:
    # An old `data-token` tag must fail visibly: served the loader instead, it would draw nothing and say nothing.
    res = await client.get("/widget/v1.js")
    assert res.status_code == 410 and "window.OpsChat" not in res.text and "/embed/v1.js" in res.text, res.text


async def test_the_embed_frame_on_the_ops_host_speaks_for_the_page_its_session_names(client: AsyncClient) -> None:
    dep = await deploy(client)
    token = await session(client, dep["id"])
    own = f"{client.base_url.scheme}://{client.base_url.netloc.decode()}"
    # The embed app's iframe is served by this host, so its calls carry this host's origin, not the intranet's.
    framed = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token, own))
    assert framed.status_code == 201, framed.text
    elsewhere = await client.post(f"/v1/widget/{dep['id']}/threads", headers=page(token, "https://evil.example"))
    assert elsewhere.status_code == 403, elsewhere.text
    # The frame's reads are same-origin GETs, which carry no Origin; the browser marks them same-origin instead.
    tid = framed.json()["data"]["id"]
    read = await client.get(
        f"/v1/widget/{dep['id']}/threads/{tid}", headers={"X-Widget-Session": token, "Sec-Fetch-Site": "same-origin"}
    )
    assert read.status_code == 200, read.text
    bare = await client.get(f"/v1/widget/{dep['id']}/threads/{tid}", headers={"X-Widget-Session": token})
    assert bare.status_code == 403, bare.text


async def test_forged_host_headers_do_not_make_a_page_the_embed_app(client: AsyncClient) -> None:
    """Only `Settings.embed_origins` names the embed app: a page that makes its origin match Host or X-Forwarded-Host
    (a proxy that forwards them, or a non-browser client) still speaks only for itself."""
    dep = await deploy(client)
    token = await session(client, dep["id"])
    evil = "https://evil.example"
    forged = {
        **page(token, evil),
        "Host": "evil.example",
        "X-Forwarded-Host": "evil.example",
        "X-Forwarded-Proto": "https",
    }
    r = await client.post(f"/v1/widget/{dep['id']}/threads", headers=forged)
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_not_allowed", r.text
