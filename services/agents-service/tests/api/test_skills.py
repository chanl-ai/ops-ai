"""/v1/skills and agent skill pins (c-063 T009, T011). Failure modes: a skill the model could never choose, or naming
a tool nobody offers, saved; a draft or deprecated version attached; a skill attached to an agent lacking a tool or
knowledge base it names, or the agent later losing one; a published version changed by a later edit; the publish
decided by its requester; a pinned skill deleted; an attached skill not reaching the served definition; a seed that
steps over a person's draft or publishes past review outside dev."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from httpx import AsyncClient

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]

LEE = {"X-Dev-User": "lee@harborpine.example"}
KIM = {"X-Dev-User": "kim@harborpine.example"}
BRANCH = "ag_branch"
HARDSHIP: dict[str, Any] = {
    "name": "Hardship request triage",
    "useWhen": "The customer says they cannot make a payment because of job loss, illness or another hardship.",
    "instructions": "Steps: confirm the customer, record the reason, offer the hardship form.",
    "ownerTeam": "Retail",
    "toolIds": ["lookup_customer"],
    "knowledgeBases": ["kb_support"],
    "guardrails": ["Never promise a payment deferral before the hardship team approves it"],
}


async def _published(c: AsyncClient, body: dict[str, Any] = HARDSHIP) -> dict[str, Any]:
    s = _ok(await c.post("/v1/skills", json=body), 201)
    return _ok(await c.post(f"/v1/skills/{s['id']}/publish-requests", json={"note": ""}), 201)


async def test_a_skill_the_model_could_not_choose_or_naming_an_unknown_tool_is_refused(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        r = await c.post("/v1/skills", json={**HARDSHIP, "useWhen": ""})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "no_use_when")
        r = await c.post("/v1/skills", json={**HARDSHIP, "toolIds": ["no_such_tool"]})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "unknown_tool")
        always = _ok(
            await c.post("/v1/skills", json={**HARDSHIP, "name": "Disclosure", "useWhen": "", "loading": "always"}), 201
        )
        assert always["loading"] == "always" and always["status"] == "draft"


async def test_only_a_published_version_attaches_and_only_to_an_agent_holding_its_scope(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        draft = _ok(await c.post("/v1/skills", json={**HARDSHIP, "name": "Draft only"}), 201)
        r = await c.put(f"/v1/agents/{BRANCH}/skills/{draft['id']}", json={"version": 1})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "not_published")

        s = await _published(c)
        r = await c.put(f"/v1/agents/ag_fraud/skills/{s['id']}", json={"version": 1})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "agent_lacks")
        assert "lookup_customer" in r.json()["error"]["message"] and "kb_support" in r.json()["error"]["message"]
        offered = _ok(await c.get("/v1/agents/ag_fraud/skills"))["available"]
        assert next(a for a in offered if a["skillId"] == s["id"])["missing"] == ["lookup_customer", "kb_support"]

        got = _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{s['id']}", json={"version": 1}))
        assert [(p["skillId"], p["pinnedVersion"]) for p in got["pins"]] == [(s["id"], 1)]
        # The agent cannot then drop a tool the pinned skill names.
        r = await c.patch(f"/v1/agents/{BRANCH}", json={"toolIds": ["request_document"]})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "skill_needs_scope")


async def test_a_published_version_never_changes_and_a_draft_edits_in_place(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c)
        d = _ok(await c.put(f"/v1/skills/{s['id']}/draft", json={"instructions": "Steps: v2.", "baseVersion": 1}))
        assert (d["version"], d["publishedVersion"], d["draftVersion"]) == (2, 1, 2)
        d = _ok(await c.put(f"/v1/skills/{s['id']}/draft", json={"instructions": "Steps: v2b.", "baseVersion": 2}))
        assert d["version"] == 2 and d["content"]["instructions"] == "Steps: v2b."
        v1 = next(v for v in d["versions"] if v["version"] == 1)
        assert (v1["state"], v1["content"]["instructions"]) == ("published", HARDSHIP["instructions"])
        r = await c.put(f"/v1/skills/{s['id']}/draft", json={"instructions": "late", "baseVersion": 1})
        assert (r.status_code, r.json()["error"]["code"]) == (409, "stale_base")


async def test_with_the_policy_off_the_requester_cannot_decide_a_skill_publish(tmp_path: Path) -> None:
    async with _app(
        str(tmp_path / "db.sqlite"), registry_auto_approve=False, dev_policies={"requesterMayDecide": False}
    ) as c:
        s = _ok(await c.post("/v1/skills", json=HARDSHIP, headers=LEE), 201)
        s = _ok(await c.post(f"/v1/skills/{s['id']}/publish-requests", json={"note": ""}, headers=LEE), 201)
        rid = s["pendingReviewId"]
        assert rid.startswith("SKP-") and s["status"] == "in_review"
        r = await c.post(f"/v1/publish-requests/{rid}/decision", json={"decision": "approved"}, headers=LEE)
        assert r.status_code == 403
        _ok(await c.post(f"/v1/publish-requests/{rid}/decision", json={"decision": "approved"}, headers=KIM))
        assert _ok(await c.get(f"/v1/skills/{s['id']}"))["publishedVersion"] == 1


async def test_a_deprecated_skill_takes_no_attach_and_a_pinned_one_is_not_deleted(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c)
        _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{s['id']}", json={"version": 1}))
        r = await c.delete(f"/v1/skills/{s['id']}")
        assert (r.status_code, r.json()["error"]["code"]) == (409, "skill_pinned")
        other = await _published(c, {**HARDSHIP, "name": "Other"})
        _ok(await c.post(f"/v1/skills/{other['id']}/deprecate", json={"reason": "Replaced"}))
        r = await c.put(f"/v1/agents/{BRANCH}/skills/{other['id']}", json={"version": 1})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "skill_deprecated")


async def test_an_attached_skill_reaches_the_served_definition_once_the_agent_publishes(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c)
        _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{s['id']}", json={"version": 1}))
        app = cast(Any, c)._transport.app
        assert app.state.runtime.catalog.agent(BRANCH).skills == [], "an attach is a draft until the agent publishes"
        v = _ok(await c.get(f"/v1/agents/{BRANCH}"))["version"]
        _ok(await c.post(f"/v1/agents/{BRANCH}/publish-requests", json={"version": v}), 201)
        served = app.state.runtime.catalog.agent(BRANCH).skills
        assert [(k.skill_id, k.version, k.slug, k.guardrails) for k in served] == [
            (s["id"], 1, "hardship-request-triage", HARDSHIP["guardrails"])
        ]


async def test_a_skill_the_published_agent_still_pins_is_not_deleted(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c)
        _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{s['id']}", json={"version": 1}))
        v = _ok(await c.get(f"/v1/agents/{BRANCH}"))["version"]
        _ok(await c.post(f"/v1/agents/{BRANCH}/publish-requests", json={"version": v}), 201)
        # Detached in a draft, still served by the published version.
        _ok(await c.delete(f"/v1/agents/{BRANCH}/skills/{s['id']}"))
        r = await c.delete(f"/v1/skills/{s['id']}")
        assert (r.status_code, r.json()["error"]["code"]) == (409, "skill_pinned")


async def test_names_and_bodies_over_their_caps_are_refused(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        r = await c.post("/v1/skills", json={**HARDSHIP, "name": "x" * 201})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "name_too_long")
        r = await c.post("/v1/skills", json={**HARDSHIP, "instructions": "x" * 24001})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "instructions_too_long")


async def test_a_body_that_could_never_load_is_not_published(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        long = {**HARDSHIP, "name": "Long", "instructions": "x" * 24000, "guardrails": ["y" * 400]}
        s = _ok(await c.post("/v1/skills", json=long), 201)
        r = await c.post(f"/v1/skills/{s['id']}/publish-requests", json={"note": ""})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "cannot_request")
        assert "could never load" in r.json()["error"]["message"]
        always = {**HARDSHIP, "name": "Long always", "loading": "always", "useWhen": "", "instructions": "x" * 9000}
        s = _ok(await c.post("/v1/skills", json=always), 201)
        r = await c.post(f"/v1/skills/{s['id']}/publish-requests", json={"note": ""})
        assert r.status_code == 400 and "2,000" in r.json()["error"]["message"]


async def test_always_on_skills_on_one_agent_stay_within_their_own_budget(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        body: dict[str, Any] = {
            **HARDSHIP,
            "loading": "always",
            "useWhen": "",
            "instructions": "x" * 4800,
            "guardrails": [],
        }
        a = await _published(c, {**body, "name": "Disclosure A"})
        b = await _published(c, {**body, "name": "Disclosure B"})
        _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{a['id']}", json={"version": 1}))
        r = await c.put(f"/v1/agents/{BRANCH}/skills/{b['id']}", json={"version": 1})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "always_budget")


async def test_a_skill_a_published_workflow_still_carries_is_not_deleted(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c)
        _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{s['id']}", json={"version": 1}))
        v = _ok(await c.get(f"/v1/agents/{BRANCH}"))["version"]
        _ok(await c.post(f"/v1/agents/{BRANCH}/publish-requests", json={"version": v}), 201)
        w = _ok(
            await c.post(
                "/v1/workflows",
                json={
                    "name": "Hardship intake",
                    "trigger": "Email",
                    "template": "approval",
                    "agentSlug": "branch-concierge",
                },
            ),
            201,
        )
        graph = _ok(await c.get(f"/v1/workflows/{w['id']}"))["draft"]["graph"]
        _ok(await c.post(f"/v1/workflows/{w['id']}/publish-requests", json={"graph": graph, "note": "go"}), 201)
        # The agent drops the skill and publishes; the workflow keeps the agent version it was published with.
        _ok(await c.delete(f"/v1/agents/{BRANCH}/skills/{s['id']}"))
        v = _ok(await c.get(f"/v1/agents/{BRANCH}"))["version"]
        _ok(await c.post(f"/v1/agents/{BRANCH}/publish-requests", json={"version": v}), 201)
        r = await c.delete(f"/v1/skills/{s['id']}")
        assert (r.status_code, r.json()["error"]["code"]) == (409, "skill_pinned"), r.text
        assert "workflow Hardship intake" in r.json()["error"]["message"]


async def test_only_the_creator_or_a_team_admin_deletes_a_skill(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = _ok(await c.post("/v1/skills", json=HARDSHIP, headers=LEE), 201)
        r = await c.delete(f"/v1/skills/{s['id']}", headers=KIM)
        assert r.status_code == 403, r.text
        assert (await c.delete(f"/v1/skills/{s['id']}", headers=LEE)).status_code == 204
