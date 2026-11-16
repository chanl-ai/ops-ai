"""The replies of the routes the console and other services call most, key by key and value by value, by failure
mode: a store row that changes its shape (a column renamed, a JSON column left as text, a datetime written another way,
a null turned into a missing key) changing what a caller is sent, an error object changing its code, a body name a
caller sends no longer accepted, and a chat turn's stream changing its frames. Generated ids and times are replaced by
their kind, so the rest is compared whole. Regenerate a fixture only for an intended change: `AGENTS_REPIN=1` writes
what the routes answer now."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast

import httpx

from tests.conftest import sse_events

from .test_guardrails import RULE
from .test_skills import HARDSHIP
from .test_widget_registry import LIMIT_CARD

FIXTURES = Path(__file__).parents[1] / "fixtures"
_TIME = re.compile(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?$")
# A generated id holds a digit, so a seeded id such as ag_fraud or a code such as role_required is compared as itself.
_ID = re.compile(r"^([a-z]+)_(?=[0-9a-zA-Z_-]*[0-9])[0-9a-zA-Z_-]{6,64}$")
# A request id: its kind's prefix and a generated tail (AGP-3f2a...).
_REQUEST = re.compile(r"^([A-Z]{2,4})-[0-9A-Za-z]{4,40}$")
# The kit's request id: its hex tail can hold no digit, which _ID needs.
_KIT_REQUEST = re.compile(r"^req_[0-9a-f]{6,64}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HEX = re.compile(r"^[0-9a-f]{16,64}$")
# Measured, so only their being numbers is compared.
_MEASURED = {"durationMs", "latencyMs", "elapsedMs", "ms", "seconds"}


def _key(k: str) -> str:
    return f"<{m.group(1)}>" if (m := _ID.match(k)) else k


def scrubbed(value: Any) -> Any:
    """`value` with every time, measured duration and generated id replaced by its kind, so two runs answer the same."""
    if isinstance(value, dict):
        held = cast(dict[str, object], value)
        return {_key(k): f"<{k}>" if k in _MEASURED and v is not None else scrubbed(v) for k, v in held.items()}
    if isinstance(value, list):
        return [scrubbed(v) for v in cast(list[object], value)]
    if isinstance(value, str):
        if m := _TIME.match(value):
            return f"<time{m.group(2) or ''}>"
        if _KIT_REQUEST.match(value):
            return "<req>"
        if m := _ID.match(value):
            return f"<{m.group(1)}>"
        if (head := value.partition(":"))[1] and (m := _ID.match(head[2])):
            return f"{head[0]}:<{m.group(1)}>"
        if m := _REQUEST.match(value):
            return f"<{m.group(1)}>"
        if _UUID.match(value):
            return "<uuid>"
        if _HEX.match(value):
            return "<hex>"
    return value


def answer(r: httpx.Response) -> dict[str, Any]:
    """The status and the whole body, scrubbed: an error's object is pinned as a success's data is."""
    return {"status": r.status_code, "body": scrubbed(r.json()) if r.content else None}


def compare(seen: dict[str, Any], pins: Path) -> None:
    if os.environ.get("AGENTS_REPIN"):
        pins.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
    assert seen == json.loads(pins.read_text()), json.dumps(seen, indent=2, sort_keys=True)


def _id(r: httpx.Response, key: str = "id") -> str:
    assert r.status_code < 300, r.text
    return r.json()["data"][key]


async def test_the_registry_replies_keep_every_key_value_and_error_object(client: httpx.AsyncClient) -> None:
    """Agents, skills, guardrails, widgets, workflows, deployments and the tool list: create, list, read, change and
    publish, with each refusal a screen shows."""
    c = client
    seen: dict[str, Any] = {}
    seen["agents.list"] = answer(await c.get("/v1/agents", params={"pageSize": 3}))
    seen["agents.read"] = answer(await c.get("/v1/agents/ag_fraud"))
    seen["agents.missing"] = answer(await c.get("/v1/agents/ag_missing"))
    made = await c.post("/v1/agents", json={"name": "Branch Desk", "role": "Answers branch questions"})
    seen["agents.create"] = answer(made)
    aid = _id(made)
    seen["agents.createRefused"] = answer(await c.post("/v1/agents", json={"role": "No name"}))
    seen["agents.update"] = answer(await c.patch(f"/v1/agents/{aid}", json={"role": "Answers branch hours"}))
    seen["agents.versions"] = answer(await c.get(f"/v1/agents/{aid}/versions"))
    seen["agents.publish"] = answer(
        await c.post(f"/v1/agents/{aid}/publish-requests", json={"version": 1, "note": "first"})
    )
    again = {"version": 1, "note": "again"}
    seen["agents.publishAgain"] = answer(await c.post(f"/v1/agents/{aid}/publish-requests", json=again))
    seen["agents.live"] = answer(await c.get(f"/v1/agents/{aid}/live"))
    seen["agents.readAfter"] = answer(await c.get(f"/v1/agents/{aid}"))

    skill = await c.post("/v1/skills", json=HARDSHIP)
    seen["skills.create"] = answer(skill)
    sid = _id(skill)
    seen["skills.createRefused"] = answer(await c.post("/v1/skills", json={**HARDSHIP, "useWhen": ""}))
    seen["skills.list"] = answer(await c.get("/v1/skills", params={"pageSize": 3}))
    seen["skills.read"] = answer(await c.get(f"/v1/skills/{sid}"))
    seen["skills.publish"] = answer(await c.post(f"/v1/skills/{sid}/publish-requests", json={"note": ""}))
    seen["skills.options"] = answer(await c.get("/v1/skills/options"))

    rule = await c.post("/v1/guardrails", json=RULE)
    seen["guardrails.create"] = answer(rule)
    gid = _id(rule)
    seen["guardrails.nameTaken"] = answer(await c.post("/v1/guardrails", json=RULE))
    seen["guardrails.list"] = answer(await c.get("/v1/guardrails", params={"pageSize": 3}))
    seen["guardrails.read"] = answer(await c.get(f"/v1/guardrails/{gid}"))
    seen["guardrails.update"] = answer(await c.patch(f"/v1/guardrails/{gid}", json={"message": "Not advice."}))

    widget = await c.post("/v1/widgets", json=LIMIT_CARD)
    seen["widgets.create"] = answer(widget)
    wid = _id(widget, "widgetId")
    seen["widgets.list"] = answer(await c.get("/v1/widgets", params={"pageSize": 3}))
    seen["widgets.read"] = answer(await c.get(f"/v1/widgets/{wid}"))
    seen["widgets.missing"] = answer(await c.get("/v1/widgets/wd_missing"))

    flow = await c.post("/v1/workflows", json={"name": "Triage", "trigger": "email"})
    seen["workflows.create"] = answer(flow)
    fid = _id(flow)
    seen["workflows.list"] = answer(await c.get("/v1/workflows", params={"pageSize": 3}))
    seen["workflows.read"] = answer(await c.get(f"/v1/workflows/{fid}"))
    seen["workflows.missing"] = answer(await c.get("/v1/workflows/wf_missing"))

    dep = {"id": "dep_pinned", "graph": "complex_workflow", "channel": "api"}
    seen["deployments.create"] = answer(await c.post("/v1/deployments", json=dep))
    seen["deployments.update"] = answer(await c.patch("/v1/deployments/dep_pinned", json={"paused": True}))
    seen["deployments.missing"] = answer(await c.patch("/v1/deployments/dep_missing", json={"paused": True}))

    seen["channels.list"] = answer(await c.get("/v1/channels"))
    seen["channels.mailboxes"] = answer(await c.get("/v1/channels/mailboxes"))
    seen["tools.list"] = answer(await c.get("/v1/tools", params={"pageSize": 3}))
    seen["tools.options"] = answer(await c.get("/v1/tools/options"))
    compare(seen, FIXTURES / "reply-pins-registry.json")


async def test_the_chat_run_and_review_replies_keep_every_key_value_and_error_object(
    client: httpx.AsyncClient,
) -> None:
    """Chat threads and their messages, graph threads, runs, the overview and Reviews, with one chat turn's stream
    pinned frame by frame (the scripted model answers the same every time)."""
    c = client
    seen: dict[str, Any] = {}
    seen["chat.agents"] = answer(await c.get("/chat/agents"))
    thread = await c.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]})
    seen["chat.createThread"] = answer(thread)
    tid = _id(thread)
    seen["chat.createRefused"] = answer(await c.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_x"]}))
    turn = await c.post(
        f"/chat/threads/{tid}/messages",
        json={"content": "What is the daily wire limit for a personal account?"},
        headers={"Accept": "text/event-stream"},
    )
    assert turn.status_code == 200, turn.text
    seen["chat.stream"] = {
        "status": turn.status_code,
        "contentType": turn.headers["content-type"].split(";")[0],
        "frames": scrubbed(sse_events(turn.text)),
    }
    seen["chat.thread"] = answer(await c.get(f"/chat/threads/{tid}"))
    seen["chat.threads"] = answer(await c.get("/chat/threads", params={"page": 1, "pageSize": 5}))
    seen["chat.missing"] = answer(await c.get("/chat/threads/th_missing"))

    graph = await c.post("/v1/threads", json={"graph": "dispute_email"})
    seen["threads.create"] = answer(graph)
    seen["threads.list"] = answer(await c.get("/v1/threads", params={"pageSize": 3}))
    seen["threads.missingState"] = answer(await c.get("/v1/threads/th_missing/state"))

    seen["runs.list"] = answer(await c.get("/v1/runs", params={"pageSize": 3}))
    seen["runs.missing"] = answer(await c.get("/v1/runs/run_missing"))
    seen["overview"] = answer(await c.get("/v1/overview"))
    seen["reviews.list"] = answer(await c.get("/reviews"))
    seen["reviews.missing"] = answer(await c.get("/reviews/th_missing"))
    compare(seen, FIXTURES / "reply-pins-runtime.json")


# The bodies the routes accept: (method, path, body). Each is sent as is, with the other spelling of its names, and
# with a key no route reads, and the three statuses are pinned: a body model moved to another base that stops taking a
# field's camelCase or snake_case name, or starts taking or refusing an unknown key, fails here.
_BODIES: list[tuple[str, str, dict[str, Any]]] = [
    ("post", "/v1/agents", {"name": "Body Desk", "role": "Answers"}),
    ("patch", "/v1/agents/ag_fraud", {"role": "Answers fraud questions", "modelAlias": "chat"}),
    ("post", "/v1/agents/ag_missing/publish-requests", {"version": 1, "note": ""}),
    ("post", "/v1/skills", {**HARDSHIP, "name": "Body skill"}),
    ("post", "/v1/guardrails", {**RULE, "name": "Body rule"}),
    ("post", "/v1/widgets", {**LIMIT_CARD, "name": "Body card"}),
    ("post", "/v1/workflows", {"name": "Body flow", "trigger": "email"}),
    ("post", "/v1/deployments", {"id": "dep_body", "graph": "complex_workflow", "channel": "api"}),
    ("post", "/chat/threads", {"agentId": "ag_fraud", "kbIds": ["kb_people"]}),
    ("post", "/v1/threads", {"graph": "dispute_email"}),
    ("post", "/v1/runs", {"workflowId": "wf_missing", "mode": "live", "input": {}, "runKey": "k1"}),
]


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()


async def test_each_body_takes_its_names_and_answers_an_unknown_key_as_today(client: httpx.AsyncClient) -> None:
    got: dict[str, Any] = {}
    for n, (method, path, body) in enumerate(_BODIES):
        other = {_snake(k): v for k, v in body.items()}
        key = f"{n:02d} {method.upper()} {path}"
        got[key] = [
            (await client.request(method, path, json=b)).status_code for b in (body, other, {**body, "teamName": "ops"})
        ]
    compare(got, FIXTURES / "reply-pins-bodies.json")
