"""Starting a workflow by hand through the API (c-466), by failure mode: the definition does not say how its trigger is
started, or names the wrong form; a form start's run gets other values than the form sent, or does not say how it
started; a viewer starts a run by hand; a trigger only its source starts is started by hand; the Start run list
offers a workflow only other workflows start, or Files offers one that takes no file. Real platform tokens, real
routes, on the app with its own database."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.test_action_roles import refused, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, VIEWER

Stack = tuple[AsyncClient, AsyncEngine]
END: dict[str, Any] = {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {}}


def workflow(wid: str, trigger: str, parameters: dict[str, Any]) -> dict[str, Any]:
    port = "payload"
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": wid.replace("_", " ").capitalize(),
        "nodes": [{"id": "start", "type": trigger, "typeVersion": 1, "parameters": parameters}, END],
        "connections": [{"from": {"node": "start", "port": port}, "to": {"node": "done", "port": "in"}}],
    }


NOTICE_FORM = {
    "type": "object",
    "required": ["notice"],
    "properties": {"notice": {"type": "string", "format": "file", "title": "Notice"}, "note": {"type": "string"}},
}
WORKFLOWS = {
    "by_email": workflow("by_email", "ops.trigger.email", {}),
    "by_form_file": workflow("by_form_file", "ops.trigger.request", {"inputSchema": NOTICE_FORM}),
    "by_form": workflow(
        "by_form", "ops.trigger.request", {"inputSchema": {"properties": {"note": {"type": "string"}}}}
    ),
    "child": workflow("child", "ops.trigger.request", {"inputSchema": NOTICE_FORM, "onlyFromWorkflows": True}),
    "on_event": workflow("on_event", "ops.trigger.event", {"event": "file.deleted"}),
}


async def saved(c: AsyncClient) -> None:
    for d in WORKFLOWS.values():
        res = await c.post("/v1/workflows/definitions", json={"definition": d}, headers=BUILDER)
        assert res.status_code == 201, res.text


async def form_of(c: AsyncClient, wid: str) -> dict[str, Any] | None:
    res = await c.get(f"/v1/workflows/definitions/{wid}", headers=BUILDER)
    assert res.status_code == 200, res.text
    return res.json()["data"]["startForm"]


async def test_each_definition_says_how_its_trigger_is_started_by_hand(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await saved(c)
    email = await form_of(c, "by_email")
    assert email is not None and (email["kind"], email["via"], email["action"]) == (
        "email",
        "test email",
        "Send test email",
    )
    assert set(email["schema"]["properties"]) == {"from", "subject", "body", "attachments"} and email["takesFiles"]
    form = await form_of(c, "by_form_file")
    assert form is not None and form["kind"] == "form" and form["schema"] == NOTICE_FORM and form["takesFiles"]
    plain = await form_of(c, "by_form")
    assert plain is not None and plain["takesFiles"] is False
    assert await form_of(c, "on_event") is None


async def test_a_form_start_runs_with_its_values_and_says_how_it_started(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await saved(c)
    values = {"note": "Received by post on 20 October"}
    res = await c.post(
        "/v1/runs/start", json={"workflowId": "by_form", "mode": "test", "values": values}, headers=BUILDER
    )
    assert res.status_code == 202, res.text
    run = (await c.get(f"/v1/runs/{res.json()['data']['runId']}", headers=BUILDER)).json()["data"]
    assert run["input"] == values and run["mode"] == "test"
    assert run["startedBy"]["via"] == {"kind": "start", "id": "form", "name": "form"}, run["startedBy"]
    assert run["startedBy"]["id"] == "james@harborpine.example"


async def test_a_viewer_starts_nothing_by_hand(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await saved(c)
    for mode in ("test", "live"):
        res = await c.post("/v1/runs/start", json={"workflowId": "by_form", "mode": mode, "values": {}}, headers=VIEWER)
        assert refused(res), (mode, res.text)


async def test_a_trigger_only_its_source_starts_is_not_started_by_hand(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await saved(c)
    res = await c.post("/v1/runs/start", json={"workflowId": "on_event", "mode": "test", "values": {}}, headers=BUILDER)
    assert res.status_code == 422 and res.json()["error"]["code"] == "no_start_form", res.text


async def listed(c: AsyncClient, query: str) -> dict[str, dict[str, Any]]:
    res = await c.get(f"/v1/workflows?pageSize=200&{query}", headers=BUILDER)
    assert res.status_code == 200, res.text
    return {w["id"]: w for w in res.json()["data"]["data"] if w["id"] in WORKFLOWS}


async def test_the_pickers_offer_what_a_person_may_start_and_what_takes_a_file(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await saved(c)
    every = await listed(c, "")
    assert set(every) == set(WORKFLOWS), "the Workflows list itself still shows every workflow"
    assert every["child"]["start"] == {"kind": "form", "byHand": False, "takesFiles": False}
    assert every["on_event"]["start"] == {"kind": "source", "byHand": False, "takesFiles": False}
    assert every["by_email"]["start"] == {"kind": "email", "byHand": True, "takesFiles": True}
    assert set(await listed(c, "startable=true")) == {"by_email", "by_form_file", "by_form"}
    assert set(await listed(c, "startable=true&takesFiles=true")) == {"by_email", "by_form_file"}
