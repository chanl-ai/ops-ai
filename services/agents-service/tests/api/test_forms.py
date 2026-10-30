"""Hosted forms (c-535), by failure mode: a public form page that shows more than the form (the team, its id); a link
submission that starts a run in another team, on a draft, or named as `form:<id>` instead of the form's title; an
expired or rotated link, or another form's token, that still starts a run; a members-only form that a person outside
the team can send; a form shared from a trigger with no inputs; every person behind the embed app counted as one
address, or a spoofed left-hand X-Forwarded-For entry trusted; a refused submission that leaves no trace in Activity.
Real routes on the app with its own database; the public routes carry no Authorization header."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from ops_agents.store.form_links import form_links
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, person

OUTSIDER = person("omar", "team_fraud", "builder")
INPUTS = {
    "type": "object",
    "required": ["account", "reason"],
    "properties": {
        "account": {"type": "string", "title": "Account number"},
        "reason": {"type": "string", "title": "Why do you need a plan?", "x-widget": "textarea"},
        "payslip": {"type": "string", "format": "file", "title": "Latest pay slip"},
    },
}
VALUES = {"account": "40 1188 2271", "reason": "Reduced hours since September"}


def flow(wid: str, inputs: dict[str, Any] | None) -> dict[str, Any]:
    params: dict[str, Any] = {"inputSchema": inputs} if inputs is not None else {}
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": "Ask for a payment plan",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": params},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


async def live(c: AsyncClient, wid: str = "payment_plan", inputs: dict[str, Any] | None = INPUTS) -> None:
    made = await c.post("/v1/workflows/definitions", json={"definition": flow(wid, inputs)}, headers=BUILDER)
    assert made.status_code == 201, made.text
    published = await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=BUILDER)
    assert published.status_code == 201, published.text


async def shared(c: AsyncClient, wid: str = "payment_plan", **settings: Any) -> dict[str, Any]:
    body = {"mode": "link", "expiresInDays": 30, "dailyCap": 100, "afterText": "Thank you.", **settings}
    r = await c.post(f"/v1/workflows/{wid}/forms", json=body, headers=BUILDER)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def send(c: AsyncClient, form: dict[str, Any], token: str | None = None, *, address: str | None = None) -> Any:
    headers = {"X-Forwarded-For": address} if address else {}
    return await c.post(
        f"/v1/forms/public/{form['slug']}/submit",
        params={"t": token or form["token"]},
        json={"values": VALUES},
        headers=headers,
    )


async def runs_of(c: AsyncClient, wid: str = "payment_plan") -> list[dict[str, Any]]:
    r = await c.get("/v1/runs", params={"workflowId": wid, "pageSize": 50}, headers=BUILDER)
    assert r.status_code == 200, r.text
    return r.json()["data"]["data"]


async def test_the_public_page_shows_only_the_form_and_a_submission_runs_in_the_forms_team(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c)
    form = await shared(c, title="Ask for a payment plan", description="Tell us what has changed.")
    page = await c.get(f"/v1/forms/public/{form['slug']}", params={"t": form["token"]})
    assert page.status_code == 200, page.text
    shown = page.json()["data"]
    assert set(shown) == {"title", "description", "form", "afterText"}, "nothing names the team before sign-in"
    assert shown["form"]["schema"] == INPUTS and "team" not in json.dumps(shown).lower(), shown
    sent = await send(c, form)
    assert sent.status_code == 202, sent.text
    [run] = await runs_of(c)
    got = (await c.get(f"/v1/runs/{run['runId'] if 'runId' in run else run['id']}", headers=BUILDER)).json()["data"]
    assert got["input"] == VALUES and got["mode"] == "live", got
    assert (got["startedBy"]["kind"], got["startedBy"]["name"]) == ("trigger", "Ask for a payment plan"), got


async def test_an_expired_or_rotated_link_or_another_forms_token_starts_nothing(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await live(c)
    first = await shared(c)
    second = await shared(c, title="A second form")
    rotated = await c.post(f"/v1/forms/{first['id']}/rotate", headers=BUILDER)
    assert rotated.status_code == 200, rotated.text
    old = await send(c, first)
    borrowed = await send(c, first, second["token"])
    with tenant_scope(TENANT):
        async with rt.db.begin() as conn:
            past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
            await conn.execute(form_links.update().where(form_links.c.id == second["id"]).values(expires_at=past))
    expired = await send(c, second)
    assert old.status_code == 401 and old.json()["error"]["code"] == "form_link_expired", old.text
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "form_link_expired", expired.text
    assert borrowed.status_code == 404, "a token opens only the form it was made for"
    assert await runs_of(c) == []


async def test_a_members_only_form_refuses_anyone_outside_its_team(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c)
    form = await shared(c, mode="members")
    outside = await c.get(f"/v1/forms/{form['slug']}/members", headers=OUTSIDER)
    inside = await c.get(f"/v1/forms/{form['slug']}/members", headers=BUILDER)
    sent = await c.post(f"/v1/forms/{form['slug']}/members", json={"values": VALUES}, headers=BUILDER)
    assert outside.status_code == 403 and outside.json()["error"]["code"] == "form_members_only", outside.text
    assert inside.status_code == 200 and sent.status_code == 202, (inside.text, sent.text)
    [run] = await runs_of(c)
    got = (await c.get(f"/v1/runs/{run.get('runId') or run['id']}", headers=BUILDER)).json()["data"]
    assert got["startedBy"]["id"] == "james@harborpine.example", got["startedBy"]
    assert got["startedBy"]["via"] == {"kind": "start", "id": "hosted_form", "name": "hosted form"}, got["startedBy"]


async def test_a_trigger_with_no_inputs_cannot_be_shared(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c, "bare", inputs=None)
    r = await c.post("/v1/workflows/bare/forms", json={"mode": "link"}, headers=BUILDER)
    assert r.status_code == 409 and r.json()["error"]["code"] == "form_needs_inputs", r.text


async def test_each_person_behind_the_proxy_is_counted_and_a_spoofed_entry_is_not_trusted(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c)
    form = await shared(c)
    first = [await send(c, form, address="203.0.113.7") for _ in range(10)]
    eleventh = await send(c, form, address="203.0.113.7")
    spoofed = await send(c, form, address="198.51.100.9, 203.0.113.7")
    someone_else = await send(c, form, address="198.51.100.9")
    assert [r.status_code for r in first] == [202] * 10, [r.text for r in first if r.status_code != 202]
    for r in (eleventh, spoofed):
        assert r.status_code == 429 and r.json()["error"]["code"] == "form_rate_limited", r.text
    assert someone_else.status_code == 202, "another person behind the same embed app is counted on their own"


async def test_a_submission_past_the_daily_cap_starts_nothing_and_activity_says_why(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c)
    form = await shared(c, dailyCap=1)
    ok = await send(c, form, address="203.0.113.7")
    capped = await send(c, form, address="203.0.113.8")
    assert ok.status_code == 202 and capped.status_code == 429, (ok.text, capped.text)
    assert capped.json()["error"]["code"] == "daily_cap", capped.text
    assert len(await runs_of(c)) == 1
    rows = (await c.get("/v1/activity", params={"kind": "form"}, headers=BUILDER)).json()["data"]["data"]
    refused = [r for r in rows if r["outcome"] == "daily_cap"]
    assert len(refused) == 1 and "daily cap" in (refused[0]["detail"] or ""), rows
