"""The console's canDecide and canCancel flags (c-123), by failure mode: a flag that says yes where the route answers
403, or no where the route lets the person act. Each flag is read for a person and then compared with what the route
does for that same person."""

from __future__ import annotations

from typing import Any, cast

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api import tool_module_reviews
from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_action_roles import (
    ADMIN,
    BUILDER,
    REVIEWER,
    SECOND_BUILDER,
    VIEWER,
    WRITE,
    live_run,
    paused_case,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
)
from tests.engine.test_lifecycle_rights import TENANT, person, unowned_live


async def flag(c: AsyncClient, url: str, key: str, who: dict[str, str]) -> Any:
    res = await c.get(url, headers=who)
    assert res.status_code == 200, res.text
    return res.json()["data"][key]


async def test_can_decide_matches_the_decision_route(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    c, _ = stack
    tid = await paused_case(c)
    url = f"/reviews/{tid}"
    flags = {
        name: await flag(c, url, "canDecide", who)
        for name, who in (("builder", SECOND_BUILDER), ("asker", BUILDER), ("reviewer", REVIEWER))
    }
    assert flags == {"builder": False, "asker": False, "reviewer": True}, flags
    body = {"decision": "rejected", "reason": "not this one"}
    refused = await c.post(f"{url}/decision", json=body, headers=SECOND_BUILDER)
    decided = await c.post(f"{url}/decision", json=body, headers=REVIEWER)
    assert refused.status_code == 403 and decided.status_code == 200, (refused.text, decided.text)
    assert await flag(c, url, "canDecide", REVIEWER) is False, "a decided review is decided by nobody"


async def test_can_decide_on_a_publish_matches_its_route(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    c, _ = stack
    made = (await c.post("/v1/agents", json={"name": "Branch Desk", "role": "Answers"}, headers=BUILDER)).json()["data"]
    req = await c.post(
        f"/v1/agents/{made['id']}/publish-requests", json={"version": made["version"], "note": "go"}, headers=BUILDER
    )
    rid = req.json()["data"]["id"]
    flags = {
        name: await flag(c, f"/reviews/{rid}", "canDecide", who)
        for name, who in (("asker", BUILDER), ("builder", SECOND_BUILDER), ("reviewer", REVIEWER))
    }
    assert flags == {"asker": False, "builder": False, "reviewer": True}, flags
    refused = await c.post(
        f"/v1/publish-requests/{rid}/decision", json={"decision": "approved"}, headers=SECOND_BUILDER
    )
    assert refused.status_code == 403, refused.text


async def test_can_cancel_matches_the_cancel_route(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    run_id = (await c.post("/v1/runs", json=live_run(1), headers=BUILDER)).json()["data"]["runId"]
    url = f"/v1/runs/{run_id}"
    flags = {
        name: await flag(c, url, "canCancel", who)
        for name, who in (
            ("starter", BUILDER),
            ("other builder", SECOND_BUILDER),
            ("viewer", VIEWER),
            ("reviewer", REVIEWER),
            ("admin", ADMIN),
        )
    }
    assert flags == {"starter": True, "other builder": False, "viewer": False, "reviewer": True, "admin": True}, flags
    listed = (await c.get("/v1/runs", headers=SECOND_BUILDER)).json()["data"]["data"]
    assert [r["canCancel"] for r in listed if r["id"] == run_id] == [False]
    refused = await c.post(f"{url}/cancel", headers=SECOND_BUILDER)
    cancelled = await c.post(f"{url}/cancel", headers=BUILDER)
    assert refused.status_code == 403 and cancelled.status_code == 200, (refused.text, cancelled.text)
    assert await flag(c, url, "canCancel", BUILDER) is False, "a cancelled run is cancelled by nobody"


async def test_can_decide_on_a_chat_approval_matches_the_route(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    c, _ = stack
    tid = (await c.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=BUILDER)).json()["data"][
        "id"
    ]
    await c.post(
        f"/chat/threads/{tid}/messages", json={"content": WRITE}, headers={**BUILDER, "Accept": "text/event-stream"}
    )
    thread: dict[str, Any] = (await c.get(f"/chat/threads/{tid}", headers=BUILDER)).json()["data"]
    messages: list[dict[str, Any]] = thread["messages"]
    widgets = [
        w for m in messages for w in cast(list[dict[str, Any]], m.get("widgets") or []) if w["kind"] == "approval"
    ]
    assert widgets and "canDecide" in widgets[-1], thread["messages"][-1]
    allowed = widgets[-1]["canDecide"]
    res = await c.post(f"/reviews/{tid}/decision", json={"decision": "approved"}, headers=BUILDER)
    assert (allowed and res.status_code == 200) or (not allowed and res.status_code == 403), (allowed, res.text)


async def test_can_decide_is_no_for_whoever_saved_the_version_of_any_saved_kind(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    """A tool module review the reviewer saved: the flag and the decision route read one list of saved kinds, and
    both refuse the saver only while the tenant's requesterMayDecide is off (c-186)."""
    c, engine = stack
    body: dict[str, Any] = {
        "moduleId": "mod_x",
        "moduleName": "X",
        "moduleVersion": "1.1.0",
        "changes": [],
        "security": False,
    }
    with tenant_scope(TENANT):
        req = await AgentRegistry(engine).open_request(
            tool_module_reviews.KIND,
            "mod_x",
            1,
            note="",
            by="james@northfield.example",
            body={**body, "teamId": "team_ops", "savedBy": "maya@northfield.example"},
            approved=False,
        )
    assert await flag(c, f"/reviews/{req['id']}", "canDecide", REVIEWER) is True
    strict = person("maya", "team_ops", "approver", policies={"requesterMayDecide": False})
    assert await flag(c, f"/reviews/{req['id']}", "canDecide", strict) is False
    decided = await c.post(f"/v1/publish-requests/{req['id']}/decision", json={"decision": "approved"}, headers=strict)
    assert decided.status_code == 403, decided.text
