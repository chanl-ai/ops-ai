"""Deciding publish requests without dev's auto-approve. Failure modes: the requester or the version's author approves
their own publish; a reject goes through with no reason; an approval does not reach chat, the graph list or new
threads; a rejected request still publishes or blocks the next request; a request is decided twice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from .test_agent_registry import _app  # pyright: ignore[reportPrivateUsage]

LEE = {"X-Dev-User": "lee@harborpine.example"}
KIM = {"X-Dev-User": "kim@harborpine.example"}


def _ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def _decide(c: AsyncClient, rid: str, decision: str, reason: str | None = None, **headers: str) -> Any:
    body = {"decision": decision} | ({"reason": reason} if reason else {})
    return await c.post(f"/v1/publish-requests/{rid}/decision", json=body, headers=headers or LEE)


async def test_an_agent_publish_waits_for_a_second_person(tmp_path: Path) -> None:
    async with _app(
        str(tmp_path / "db.sqlite"), registry_auto_approve=False, dev_policies={"requesterMayDecide": False}
    ) as c:
        # Lee saves the version, the dev user asks to publish it, and Kim is the only one left who may decide.
        new = {"name": "Checker", "role": "Checks"}
        agent = _ok(await c.post("/v1/agents", json=new, headers=LEE), 201)
        review = _ok(await c.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": 1, "note": "go"}), 201)
        assert review["status"] == "pending"

        own = await c.post(f"/v1/publish-requests/{review['id']}/decision", json={"decision": "approved"})
        assert (own.status_code, own.json()["error"]["code"]) == (403, "own_request"), own.text
        author = await _decide(c, review["id"], "approved")
        assert (author.status_code, author.json()["error"]["code"]) == (403, "own_request"), author.text
        assert agent["id"] not in {a["id"] for a in _ok(await c.get("/chat/agents"))}

        decided = _ok(await _decide(c, review["id"], "approved", **KIM))
        assert decided["status"] == "approved" and decided["approvals"] == ["kim@harborpine.example"]
        assert agent["id"] in {a["id"] for a in _ok(await c.get("/chat/agents"))}
        assert f"agent:{agent['id']}" in {g["name"] for g in _ok(await c.get("/v1/graphs"))}
        again = await _decide(c, review["id"], "rejected", "late")
        assert again.status_code == 409 and again.json()["error"]["code"] == "already_decided"


async def test_a_rejected_workflow_publish_needs_a_reason_and_publishes_nothing(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite"), registry_auto_approve=False) as c:
        body = {"name": "Payee", "trigger": "Payee added", "template": "approval", "agentSlug": "wire-fraud-sentinel"}
        wf = _ok(await c.post("/v1/workflows", json=body), 201)
        graph = _ok(await c.get(f"/v1/workflows/{wf['id']}"))["draft"]["graph"]
        first = _ok(await c.post(f"/v1/workflows/{wf['id']}/publish-requests", json={"graph": graph, "note": "a"}), 201)
        assert "definition" not in first["publish"], "the stored definition stays out of the console's view"

        no_reason = await _decide(c, first["id"], "rejected")
        assert no_reason.status_code == 400 and no_reason.json()["error"]["code"] == "reason_required"
        rejected = _ok(await _decide(c, first["id"], "rejected", "Missing a fraud check"))
        assert rejected["status"] == "rejected" and rejected["decisionReason"] == "Missing a fraud check"
        assert (await c.post("/v1/threads", json={"graph": wf["id"]})).status_code == 400

        second = _ok(
            await c.post(f"/v1/workflows/{wf['id']}/publish-requests", json={"graph": graph, "note": "b"}), 201
        )
        _ok(await _decide(c, second["id"], "approved"))
        started = await c.post("/v1/threads", json={"graph": wf["id"]})
        assert started.status_code == 201 and started.json()["data"]["version"] == 1, started.text
        assert _ok(await c.get(f"/v1/workflows/{wf['id']}"))["status"] == "live"


async def test_reviews_list_and_decide_publish_requests_under_the_publish_rules(tmp_path: Path) -> None:
    # The console's Reviews page reads one list; a publish request is a row there and is decided from there, held to
    # the same rules as its own decide route.
    async with _app(
        str(tmp_path / "db.sqlite"), registry_auto_approve=False, dev_policies={"requesterMayDecide": False}
    ) as c:
        new = {"name": "Checker", "role": "Checks"}
        agent = _ok(await c.post("/v1/agents", json=new, headers=LEE), 201)
        rid = _ok(await c.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": 1, "note": "go"}), 201)[
            "id"
        ]

        listed = _ok(await c.get("/reviews", params={"view": "open", "page": 1, "pageSize": 50}))
        row = next(r for r in listed["data"] if r["id"] == rid)
        assert row["kind"] == "agent_publish" and row["status"] == "pending"
        assert listed["viewCounts"]["open"] >= 1 and listed["facets"]["kind"].get("agent_publish") == 1
        assert _ok(await c.get(f"/reviews/{rid}"))["id"] == rid

        own = await c.post(f"/reviews/{rid}/decision", json={"decision": "approved"})
        assert own.status_code == 403, own.text
        no_reason = await c.post(f"/reviews/{rid}/decision", json={"decision": "returned"}, headers=KIM)
        assert no_reason.status_code == 400 and no_reason.json()["error"]["code"] == "reason_required"
        decided = _ok(await c.post(f"/reviews/{rid}/decision", json={"decision": "approved"}, headers=KIM))
        assert decided["status"] == "approved"
        assert agent["id"] in {a["id"] for a in _ok(await c.get("/chat/agents"))}
        again = await c.post(f"/reviews/{rid}/decision", json={"decision": "approved"}, headers=KIM)
        assert again.status_code == 409
        resolved = _ok(await c.get("/reviews", params={"view": "resolved", "page": 1, "pageSize": 50}))
        assert rid in {r["id"] for r in resolved["data"]}
