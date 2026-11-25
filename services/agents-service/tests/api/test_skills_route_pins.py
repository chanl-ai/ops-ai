"""Every /v1/skills and /v1/agents/{id}/skills route's reply, status and error object, value by value, by failure
mode: a skill, page or picker reply changing a key or a value the Skills page, the agent page or the MCP prompts read;
a refusal (a viewer, another team, a stale base, a deprecated or pinned skill) changing its status or code, so a change
that was refused is let through or a page cannot say why. Regenerate with `AGENTS_REPIN=1` only for an intended
change."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient

from ops_agents.api import publish_policy
from tests.api.test_reply_pins import FIXTURES, compare
from tests.api.test_widget_embed import BUILDER, OUTSIDER, VIEWER
from tests.api.test_widget_route_pins import answer, client  # pyright: ignore[reportPrivateUsage]
from tests.api.test_widgets_route_pins import _transactions  # pyright: ignore[reportPrivateUsage]
from tests.saves import save_skill_draft

__all__ = ["client"]

SKILL: dict[str, Any] = {
    "name": "Hardship request triage",
    "useWhen": "The customer says they cannot make a payment because of job loss, illness or another hardship.",
    "instructions": "Steps: confirm the customer, record the reason as {reason}, offer the hardship form.",
    "inputs": [{"name": "reason", "required": True}],
}
AGENT = "ag_fraud"


async def test_every_skills_route_keeps_its_reply_status_and_error_object(client: AsyncClient) -> None:
    c, seen = client, dict[str, Any]()
    made = await c.post("/v1/skills", json=SKILL, headers=BUILDER)
    seen["create"] = answer(made)
    sid = made.json()["data"]["id"]
    for i in range(3):
        await c.post("/v1/skills", json={**SKILL, "name": f"Same name {i}"}, headers=BUILDER)
    seen["create.viewer"] = answer(await c.post("/v1/skills", json={**SKILL, "name": "x"}, headers=VIEWER))
    seen["create.noUseWhen"] = answer(await c.post("/v1/skills", json={**SKILL, "useWhen": ""}, headers=BUILDER))
    seen["create.unknownField"] = answer(await c.post("/v1/skills", json={**SKILL, "x": 1}, headers=BUILDER))

    url = f"/v1/skills/{sid}"
    seen["read"] = answer(await c.get(url, headers=BUILDER))
    seen["read.missing"] = answer(await c.get("/v1/skills/sk_missing", headers=BUILDER))
    seen["read.otherTeam"] = answer(await c.get(url, headers=OUTSIDER))

    draft = {"instructions": "Steps: confirm, record {reason}, offer the form."}
    seen["draft"] = answer(await save_skill_draft(c, sid, draft, headers=BUILDER))
    # The refused callers cannot read the skill, and each save changes the newest copy, so the builder reads the base.
    seen["draft.stale"] = answer(await save_skill_draft(c, sid, {**draft, "baseVersion": 9}, headers=BUILDER))
    seen["draft.viewer"] = answer(await save_skill_draft(c, sid, draft, headers=VIEWER, read_as=BUILDER))
    seen["draft.otherTeam"] = answer(await save_skill_draft(c, sid, draft, headers=OUTSIDER, read_as=BUILDER))

    seen["publish"] = answer(await c.post(f"{url}/publish-requests", json={"note": "first"}, headers=BUILDER))
    seen["publish.again"] = answer(await c.post(f"{url}/publish-requests", json={}, headers=BUILDER))
    seen["publish.viewer"] = answer(await c.post(f"{url}/publish-requests", json={}, headers=VIEWER))

    seen["render"] = answer(await c.post(f"{url}/render", json={"inputs": {"reason": "job loss"}}, headers=BUILDER))
    seen["render.missingInput"] = answer(await c.post(f"{url}/render", json={}, headers=BUILDER))
    seen["render.otherTeam"] = answer(await c.post(f"{url}/render", json={}, headers=OUTSIDER))

    seen["list"] = answer(await c.get("/v1/skills", headers=BUILDER))
    seen["list.page"] = answer(await c.get("/v1/skills", params={"page": 2, "pageSize": 2}, headers=BUILDER))
    seen["list.pastTheEnd"] = answer(await c.get("/v1/skills", params={"page": 9, "pageSize": 2}, headers=BUILDER))
    seen["list.search"] = answer(await c.get("/v1/skills", params={"search": "hardship"}, headers=BUILDER))
    seen["list.published"] = answer(await c.get("/v1/skills", params={"view": "published"}, headers=BUILDER))
    seen["list.facet"] = answer(await c.get("/v1/skills", params={"status": "draft"}, headers=BUILDER))
    seen["list.otherTeam"] = answer(await c.get("/v1/skills", headers=OUTSIDER))
    seen["list.agent"] = answer(
        await c.get("/v1/skills", params={"usableBy": "agent", "agentId": AGENT}, headers=BUILDER)
    )
    seen["options"] = answer(await c.get("/v1/skills/options", headers=BUILDER))

    agent = f"/v1/agents/{AGENT}/skills"
    seen["agent.options"] = answer(await c.get(f"{agent}/options", headers=BUILDER))
    seen["agent.optionsSearch"] = answer(await c.get(f"{agent}/options", params={"search": "nothing"}, headers=BUILDER))
    seen["attach"] = answer(await c.put(f"{agent}/{sid}", json={}, headers=BUILDER))
    seen["attach.draftOnly"] = answer(await c.put(f"{agent}/sk_missing", json={}, headers=BUILDER))
    seen["attach.viewer"] = answer(await c.put(f"{agent}/{sid}", json={}, headers=VIEWER))
    seen["agent.skills"] = answer(await c.get(agent, headers=BUILDER))
    seen["agent.missing"] = answer(await c.get("/v1/agents/ag_missing/skills", headers=BUILDER))
    seen["delete.pinned"] = answer(await c.delete(url, headers=BUILDER))
    seen["detach"] = answer(await c.delete(f"{agent}/{sid}", headers=BUILDER))
    seen["detach.notHeld"] = answer(await c.delete(f"{agent}/{sid}", headers=BUILDER))

    seen["deprecate.noReason"] = answer(await c.post(f"{url}/deprecate", json={"reason": " "}, headers=BUILDER))
    seen["deprecate.viewer"] = answer(await c.post(f"{url}/deprecate", json={"reason": "Old"}, headers=VIEWER))
    seen["deprecate"] = answer(await c.post(f"{url}/deprecate", json={"reason": "Old"}, headers=BUILDER))
    seen["draft.deprecated"] = answer(await save_skill_draft(c, sid, {**draft, "baseVersion": 2}, headers=BUILDER))
    seen["delete.viewer"] = answer(await c.delete(url, headers=VIEWER))
    seen["delete"] = answer(await c.delete(url, headers=BUILDER))
    # The new skill's id is random; the scrubber hides it in ids but not inside a message.
    compare(json.loads(json.dumps(seen).replace(sid, "<sk>")), FIXTURES / "reply-pins-skills.json")


async def test_each_skills_route_on_the_database_alone_holds_one_transaction(client: AsyncClient) -> None:
    """A route opening one transaction per store call: a save whose refusal checks and write land apart, a delete
    whose pin check and removal land apart, or a page whose rows and counts are read at different moments. Create
    and draft save write in one transaction after the tool check."""
    c = client
    sid = (await c.post("/v1/skills", json=SKILL, headers=BUILDER)).json()["data"]["id"]
    await c.post(f"/v1/skills/{sid}/publish-requests", json={}, headers=BUILDER)
    url, agent = f"/v1/skills/{sid}", f"/v1/agents/{AGENT}/skills"
    draft = {"instructions": "Steps {reason}."}
    steps: list[tuple[str, str, str, object]] = [
        ("create", "POST", "/v1/skills", {**SKILL, "name": "Second"}),
        ("list", "GET", "/v1/skills?page=1&pageSize=2", None),
        ("read", "GET", url, None),
        ("render", "POST", f"{url}/render", {"inputs": {"reason": "illness"}}),
        ("draft", "PUT", f"{url}/draft", draft),
        ("agent.options", "GET", f"{agent}/options", None),
        ("attach", "PUT", f"{agent}/{sid}", {}),
        ("agent.skills", "GET", agent, None),
        ("detach", "DELETE", f"{agent}/{sid}", None),
        ("deprecate", "POST", f"{url}/deprecate", {"reason": "Old"}),
        ("delete", "DELETE", url, None),
    ]
    held = _transactions()
    counts: dict[str, int] = {}
    for name, method, path, body in steps:
        sent = body
        if name == "draft":  # the save names the copy just read
            opened = (await c.get(url, headers=BUILDER)).json()["data"]
            sent = {**draft, "baseVersion": opened["version"], "baseDigest": opened["digest"]}
        held[0] = 0
        r = await c.request(method, path, json=sent, headers=BUILDER)
        assert r.status_code in (200, 201, 204), (name, r.text)
        counts[name] = held[0]
    assert counts == {name: 1 for name, *_ in steps} | {"draft": 2}, counts


async def test_no_transaction_is_open_while_another_service_answers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool directory (tools-service) is read by the options route and the tool check on a create or a draft
    save, and a publish request reads the publish-review policy (platform-service): a request transaction held across
    either holds a connection for as long as the other service takes."""
    from ops_agents.api.routers import tool_catalog  # noqa: PLC0415 - patched where the routes look it up

    c = client
    held, open_during = _transactions(), list[tuple[str, int]]()
    tools, policy = tool_catalog.known_tools, publish_policy.team_document

    directory = tool_catalog.directory_tools

    async def known(
        rt: Any, *, fresh: bool = False, listed: tool_catalog.ToolRows | None = None
    ) -> tool_catalog.ToolRows:
        if listed is None:  # rows from a directory the route already asked hold no outside call
            open_during.append(("tools", held[1]))
        return await tools(rt, fresh=fresh, listed=listed)

    async def asked_directory(rt: Any, *, fresh: bool = False) -> tool_catalog.ToolRows:
        open_during.append(("tools", held[1]))
        return await directory(rt, fresh=fresh)

    async def document(rt: Any) -> dict[str, Any] | None:
        open_during.append(("policy", held[1]))
        return await policy(rt)

    monkeypatch.setattr(tool_catalog, "known_tools", known)
    monkeypatch.setattr(publish_policy, "team_document", document)
    import ops_agents.api.skills as skills_api  # noqa: PLC0415

    monkeypatch.setattr(skills_api, "known_tools", known)
    from ops_agents.api.routers import skills as skills_routes  # noqa: PLC0415

    monkeypatch.setattr(skills_routes, "known_tools", known)
    monkeypatch.setattr(skills_routes, "directory_tools", asked_directory)
    tool = {"toolIds": ["lookup_account"]}
    made = await c.post("/v1/skills", json={**SKILL, **tool}, headers=BUILDER)
    sid = made.json()["data"]["id"]
    saved = await save_skill_draft(c, sid, tool, headers=BUILDER)
    asked = await c.post(f"/v1/skills/{sid}/publish-requests", json={}, headers=BUILDER)
    options = await c.get("/v1/skills/options", headers=BUILDER)
    statuses = (made.status_code, saved.status_code, asked.status_code, options.status_code)
    assert statuses == (201, 200, 201, 200), (made.text, saved.text)
    assert open_during == [("tools", 0), ("tools", 0), ("policy", 0), ("tools", 0)], open_during
