"""Every widget route's reply, status and error object, value by value, by failure mode: a deployment, key, audit or
session reply changing a key or a value the console, the embed app or a bank's server reads; a refusal on the mint key,
session or message path changing its status or code, so a credential that was refused is let through or a page cannot
say why. Session tokens and key secrets are replaced by their kind; the rest is compared whole. Regenerate with
`AGENTS_REPIN=1` only for an intended change."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api import test_write_approval_policy as platform_stub
from tests.api.test_reply_pins import FIXTURES, compare, scrubbed
from tests.api.test_widget_embed import (
    BANKER,
    BUILDER,
    INTRANET,
    OPS_KEY,
    OUTSIDER,
    SETTINGS,
    VIEWER,
    introspect,
    page,
)
from tests.api.test_write_approval_policy import _client  # pyright: ignore[reportPrivateUsage]
from tests.conftest import sse_events

CONSOLE = "http://localhost:3016"
# Generated per call and checked by their own tests: a session token and a mint key's secret.
_SECRETS = {"session", "secret"}


def _hidden(value: Any) -> Any:
    if isinstance(value, dict):
        held = cast(dict[str, object], value)
        return {k: f"<{k}>" if k in _SECRETS and isinstance(v, str) else _hidden(v) for k, v in held.items()}
    if isinstance(value, list):
        return [_hidden(v) for v in cast(list[object], value)]
    return value


def answer(r: Response) -> dict[str, Any]:
    body = _hidden(scrubbed(r.json())) if r.content else None
    return {"status": r.status_code, "body": body}


# The engine each test's app is built on, so a test can count the transactions a request opens.
_ENGINES: list[AsyncEngine] = []


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(platform_stub, "introspect", introspect)
    made = platform_stub.create_async_engine

    def kept(*args: Any, **kwargs: Any) -> AsyncEngine:
        _ENGINES.append(engine := made(*args, **kwargs))
        return engine

    monkeypatch.setattr(platform_stub, "create_async_engine", kept)
    async for c in _client(SETTINGS.model_copy(update={"console_url": CONSOLE}), platform=True):
        yield c


async def test_every_widget_route_keeps_its_reply_status_and_error_object(client: AsyncClient) -> None:
    c, seen = client, dict[str, Any]()
    base = "/v1/widget-deployments"
    made = await c.post(
        base, json={"name": "Intranet help", "agentId": "ag_fraud", "origins": [INTRANET]}, headers=BUILDER
    )
    seen["deployments.create"] = answer(made)
    dep = made.json()["data"]["id"]
    seen["deployments.createViewer"] = answer(
        await c.post(base, json={"name": "x", "agentId": "ag_fraud", "origins": [INTRANET]}, headers=VIEWER)
    )
    seen["deployments.createUnknownField"] = answer(
        await c.post(base, json={"name": "x", "agentId": "ag_fraud", "origins": [INTRANET], "x": 1}, headers=BUILDER)
    )
    seen["deployments.list"] = answer(await c.get(base, params={"agentId": "ag_fraud"}, headers=BUILDER))
    seen["deployments.listOtherAgent"] = answer(await c.get(base, params={"agentId": "ag_other"}, headers=BUILDER))

    keys = f"{base}/{dep}/keys"
    key = await c.post(keys, json={"name": "Intranet server"}, headers=BUILDER)
    seen["keys.create"] = answer(key)
    secret, key_id = key.json()["data"]["secret"], key.json()["data"]["key"]["id"]
    seen["keys.createTooLong"] = answer(await c.post(keys, json={"name": "x", "expiresInDays": 400}, headers=BUILDER))
    seen["keys.createOtherTeam"] = answer(await c.post(keys, json={"name": "x"}, headers=OUTSIDER))
    seen["keys.list"] = answer(await c.get(keys, headers=BUILDER))
    seen["keys.listMissing"] = answer(await c.get(f"{base}/wd_missing/keys", headers=BUILDER))

    mint = f"{base}/{dep}/sessions"
    person = {"email": "banker@bank.example", "name": "Banker", "origin": INTRANET}
    bearer = {"Authorization": f"Bearer {secret}"}
    seen["mint.session"] = answer(await c.post(mint, json=person, headers=bearer))
    seen["mint.teamKey"] = answer(await c.post(mint, json=person, headers=OPS_KEY))
    seen["mint.personToken"] = answer(await c.post(mint, json=person, headers=BUILDER))
    seen["mint.forged"] = answer(await c.post(mint, json=person, headers={"Authorization": f"Bearer {secret}xx"}))
    seen["mint.otherDeployment"] = answer(await c.post(f"{base}/wd_other/sessions", json=person, headers=bearer))
    seen["mint.unlistedOrigin"] = answer(
        await c.post(mint, json={**person, "origin": "https://evil.example"}, headers=bearer)
    )
    seen["mint.unknownField"] = answer(await c.post(mint, json={**person, "teamId": "team_ops"}, headers=bearer))

    seen["preview.session"] = answer(await c.post(f"{base}/{dep}/preview-session", headers=BUILDER))
    seen["preview.viewer"] = answer(await c.post(f"{base}/{dep}/preview-session", headers=VIEWER))
    seen["preview.apiKey"] = answer(await c.post(f"{base}/{dep}/preview-session", headers=OPS_KEY))

    widget = f"/v1/widget/{dep}"
    opened = await c.post(f"{widget}/session", headers={**BANKER, "Origin": INTRANET})
    seen["page.session"] = answer(opened)
    token = opened.json()["data"]["session"]
    seen["page.sessionUnlisted"] = answer(
        await c.post(f"{widget}/session", headers={**BANKER, "Origin": "https://e.x"})
    )
    seen["page.sessionOtherTeam"] = answer(await c.post(f"{widget}/session", headers={**OUTSIDER, "Origin": INTRANET}))
    seen["page.sessionApiKey"] = answer(await c.post(f"{widget}/session", headers={**OPS_KEY, "Origin": INTRANET}))
    seen["page.sessionMissing"] = answer(
        await c.post("/v1/widget/wd_missing/session", headers={**BANKER, "Origin": INTRANET})
    )

    thread = await c.post(f"{widget}/threads", headers=page(token))
    seen["threads.create"] = answer(thread)
    tid = thread.json()["data"]["id"]
    seen["threads.createNoSession"] = answer(await c.post(f"{widget}/threads", headers={"Origin": INTRANET}))
    seen["threads.createMovedOrigin"] = answer(
        await c.post(f"{widget}/threads", headers=page(token, "https://portal.bank.example"))
    )
    seen["threads.read"] = answer(await c.get(f"{widget}/threads/{tid}", headers=page(token)))
    seen["threads.readMissing"] = answer(await c.get(f"{widget}/threads/th_missing", headers=page(token)))

    turn = await c.post(
        f"{widget}/threads/{tid}/messages",
        json={"content": "What is the daily wire limit for a personal account?"},
        headers={**page(token), "Accept": "text/event-stream"},
    )
    seen["messages.stream"] = {
        "status": turn.status_code,
        "contentType": turn.headers["content-type"].split(";")[0],
        "frames": scrubbed(sse_events(turn.text)),
    }
    seen["messages.regenerate"] = answer(
        await c.post(f"{widget}/threads/{tid}/messages", json={"content": "x", "regenerate": True}, headers=page(token))
    )
    seen["messages.overrides"] = answer(
        await c.post(
            f"{widget}/threads/{tid}/messages",
            json={"content": "x", "overrides": {"temperature": 0.5}},
            headers=page(token),
        )
    )
    seen["messages.otherThread"] = answer(
        await c.post(f"{widget}/threads/th_missing/messages", json={"content": "x"}, headers=page(token))
    )
    seen["budget.notPaused"] = answer(
        await c.post(f"{widget}/threads/{tid}/budget", json={"action": "continue"}, headers=page(token))
    )

    config = f"{widget}/config"
    seen["config.page"] = answer(await c.get(config, params={"tenant": "local"}, headers={"Origin": INTRANET}))
    seen["config.key"] = answer(await c.get(config, params={"tenant": "local"}, headers=bearer))
    seen["config.console"] = answer(await c.get(config, params={"tenant": "local"}, headers={"Origin": CONSOLE}))
    seen["config.unlisted"] = answer(await c.get(config, params={"tenant": "local"}, headers={"Origin": "https://e.x"}))
    seen["config.otherTenant"] = answer(await c.get(config, params={"tenant": "other"}, headers={"Origin": INTRANET}))

    seen["keys.revoke"] = answer(await c.post(f"{keys}/{key_id}/revoke", headers=BUILDER))
    seen["keys.revokeMissing"] = answer(await c.post(f"{keys}/wkk_missing1/revoke", headers=BUILDER))
    seen["mint.revoked"] = answer(await c.post(mint, json=person, headers=bearer))
    seen["keys.audit"] = answer(await c.get(f"{keys}/audit", headers=BUILDER))
    seen["keys.auditOtherTeam"] = answer(await c.get(f"{keys}/audit", headers=OUTSIDER))

    loader, retired = await c.get("/embed/v1.js"), await c.get("/widget/v1.js")
    seen["loader"] = [loader.status_code, loader.headers["content-type"], loader.headers["cache-control"]]
    seen["retired"] = [retired.status_code, retired.text]
    compare(seen, FIXTURES / "reply-pins-widget.json")


async def test_each_widget_route_on_the_database_alone_holds_one_transaction(client: AsyncClient) -> None:
    """A route opening one transaction per store call: a mint whose key check and last-use write land apart, or a
    deployment page read from rows of different moments."""
    c, base = client, "/v1/widget-deployments"
    new = {"name": "Intranet help", "agentId": "ag_fraud", "origins": [INTRANET]}
    dep = (await c.post(base, json=new, headers=BUILDER)).json()["data"]["id"]
    made = (await c.post(f"{base}/{dep}/keys", json={"name": "Server"}, headers=BUILDER)).json()["data"]
    bearer = {"Authorization": f"Bearer {made['secret']}"}
    person = {"email": "banker@bank.example", "name": "Banker", "origin": INTRANET}
    token = (await c.post(f"/v1/widget/{dep}/session", headers={**BANKER, "Origin": INTRANET})).json()["data"]
    tid = (await c.post(f"/v1/widget/{dep}/threads", headers=page(token["session"]))).json()["data"]["id"]
    steps: list[tuple[str, str, str, object, dict[str, str]]] = [
        ("create", "POST", base, new, BUILDER),
        ("list", "GET", base, None, BUILDER),
        ("key", "POST", f"{base}/{dep}/keys", {"name": "Other"}, BUILDER),
        ("keys", "GET", f"{base}/{dep}/keys", None, BUILDER),
        ("preview", "POST", f"{base}/{dep}/preview-session", None, BUILDER),
        ("audit", "GET", f"{base}/{dep}/keys/audit", None, BUILDER),
        ("mint", "POST", f"{base}/{dep}/sessions", person, bearer),
        ("page session", "POST", f"/v1/widget/{dep}/session", None, {**BANKER, "Origin": INTRANET}),
        ("thread", "GET", f"/v1/widget/{dep}/threads/{tid}", None, page(token["session"])),
        ("config", "GET", f"/v1/widget/{dep}/config?tenant=local", None, {"Origin": INTRANET}),
        ("revoke", "POST", f"{base}/{dep}/keys/{made['key']['id']}/revoke", None, BUILDER),
    ]
    begun: list[int] = []

    def began(_conn: object) -> None:
        begun.append(1)

    event.listen(_ENGINES[-1].sync_engine, "begin", began)
    counts: dict[str, int] = {}
    for name, method, path, body, headers in steps:
        begun.clear()
        r = await c.request(method, path, json=body, headers=headers)
        assert r.status_code in (200, 201), (name, r.text)
        counts[name] = len(begun)
    assert counts == {name: 1 for name, *_ in steps}, counts
