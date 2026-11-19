"""A skill's steps through /v1/skills and the agent's pins, by failure mode: a save dropping the steps, exits,
results, not-when or success lines, storing a mistyped rule as a check the model judges, or saving a skill that cannot
run; a pin losing the steps, or a pin saved before steps no longer loading; a skill publishing while a step names a
tool the team no longer offers, or the refusal not saying which step.

Where the design names no shape, these tests fix one: a refused step answers its 1-based position as
`error.details.step`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from httpx import AsyncClient

from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tool_directory import CatalogTools
from ops_agents.api.agent_registry import definition_of
from tests.conftest import SEED

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]
from .test_stale_grants import Directory

BRANCH = "ag_branch"
LOOKUP = {"kind": "tool", "id": "lookup_customer"}
REFUND: dict[str, Any] = {
    "name": "Refund a charge",
    "useWhen": "The customer asks for a card charge to be refunded.",
    "instructions": "Quote the amount back before any refund.",
    "ownerTeam": "Retail",
    "toolIds": ["lookup_customer"],
}
STEPS: list[dict[str, Any]] = [
    {
        "do": "Look up the customer and the charge.",
        "use": LOOKUP,
        # The server decides who judges a check; what the client sends for `by` is replaced.
        "check": {"text": "result.amount <= 500", "by": "model"},
        "ifNot": {"action": "retry", "retries": 2},
    },
    {
        "do": "Tell the person the amount and ask them to confirm.",
        "check": {"text": "The person confirmed the amount."},
        "ifNot": {"action": "exit", "exit": "escalate"},
    },
]
PROGRAM: dict[str, Any] = {
    "steps": STEPS,
    "exit": {"escalate": "Hand the request to a person."},
    "returns": [{"name": "refunded", "type": "yes_no"}],
    "notWhen": "The charge is older than 120 days.",
    "success": ["The person was told the amount before the refund."],
}


def _step(n: int, **change: Any) -> list[dict[str, Any]]:
    """STEPS with step `n` (1-based) changed."""
    return [{**s, **change} if i == n else s for i, s in enumerate(STEPS, start=1)]


def _error(r: Any) -> dict[str, Any]:
    assert r.status_code == 400, r.text
    return cast(dict[str, Any], r.json()["error"])


async def _published(c: AsyncClient, body: dict[str, Any]) -> str:
    s = _ok(await c.post("/v1/skills", json=body), 201)
    _ok(await c.post(f"/v1/skills/{s['id']}/publish-requests", json={"note": ""}), 201)
    return str(s["id"])


async def test_a_save_keeps_the_steps_and_refuses_a_mistyped_rule_or_a_skill_that_cannot_run(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        sid = _ok(await c.post("/v1/skills", json=REFUND), 201)["id"]
        url = f"/v1/skills/{sid}/draft"
        _ok(await c.put(url, json={**PROGRAM, "baseVersion": 1}))
        content = _ok(await c.get(f"/v1/skills/{sid}"))["content"]
        first, second = content["steps"]
        assert (first["do"], first["use"]) == (STEPS[0]["do"], LOOKUP)
        assert first["check"] == {"text": "result.amount <= 500", "by": "rule"}
        assert second["check"] == {"text": "The person confirmed the amount.", "by": "model"}
        assert (first["ifNot"]["action"], first["ifNot"]["retries"]) == ("retry", 2)
        assert (second["ifNot"]["action"], second["ifNot"]["exit"]) == ("exit", "escalate")
        assert content["exit"] == PROGRAM["exit"]
        assert [(r["name"], r["type"]) for r in content["returns"]] == [("refunded", "yes_no")]
        assert (content["notWhen"], content["success"]) == (PROGRAM["notWhen"], PROGRAM["success"])

        # A text that reads as a rule and is not a valid one is refused, with its step: stored as a sentence it would
        # be a check the model judges. A rule reads the step's own result and the inputs, never an earlier step.
        for text in ("reslt.amount <= 500", "result.amount =< 500", "steps[1].amount <= 500"):
            error = _error(await c.put(url, json={"steps": _step(1, check={"text": text}), "baseVersion": 1}))
            assert (error["code"], error["details"]["step"]) == ("bad_check", 1), (text, error)

        plain = await _published(c, {**REFUND, "name": "Plain look-up"})
        # A published skill whose own step runs a skill: one level of sub-skill is the most a step may start.
        nested = await _published(
            c, {**REFUND, "name": "Nested", "steps": [{"do": "Look up.", "use": {"kind": "skill", "id": plain}}]}
        )
        cannot_run: dict[str, dict[str, Any]] = {
            "bad_goto": {"steps": _step(1, ifNot={"action": "goto", "step": 9})},
            "unknown_exit": {"steps": _step(1, ifNot={"action": "exit", "exit": "vanish"})},
            "steps_and_parts": {
                "parts": [{"slug": "late", "name": "Late", "useWhen": "Late.", "instructions": "Say sorry."}]
            },
            "steps_always_on": {"loading": "always", "useWhen": ""},
            "unknown_reference": {"steps": _step(2, use={"kind": "skill", "id": "sk_missing"})},
            "sub_skill_depth": {"steps": _step(2, use={"kind": "skill", "id": nested})},
        }
        for code, change in cannot_run.items():
            error = _error(await c.put(url, json={**change, "baseVersion": 1}))
            assert error["code"] == code, (code, error)
        to_itself = _step(1, ifNot={"action": "goto", "step": 1})
        own_step = _error(await c.put(url, json={"steps": to_itself, "baseVersion": 1}))
        assert own_step["code"] == "bad_goto", own_step
        # A step runs a tool, a skill, an agent or a workflow; a knowledge base is only ever mentioned in its text.
        searches = _step(2, use={"kind": "knowledge", "id": "kb_support"})
        _error(await c.put(url, json={"steps": searches, "baseVersion": 1}))

        # A published skill whose new draft has a step that runs the skill itself.
        _ok(await c.post(f"/v1/skills/{sid}/publish-requests", json={"note": ""}), 201)
        itself = _error(await c.put(url, json={"steps": _step(2, use={"kind": "skill", "id": sid}), "baseVersion": 1}))
        assert itself["code"] == "sub_skill_cycle", itself

        kept = _ok(await c.get(f"/v1/skills/{sid}"))
        assert kept["version"] == 1 and kept["content"]["steps"] == content["steps"], "a refused save stored nothing"


async def test_an_attached_skill_runs_with_its_steps_and_a_pin_saved_before_steps_still_loads(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        sid = await _published(c, {**REFUND, **PROGRAM})
        _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{sid}", json={"version": 1}))
        version = _ok(await c.get(f"/v1/agents/{BRANCH}"))["version"]
        _ok(await c.post(f"/v1/agents/{BRANCH}/publish-requests", json={"version": version}), 201)
        catalog = cast(Any, c)._transport.app.state.runtime.catalog
        (skill,) = catalog.settings_for(catalog.agent(BRANCH), "m").skills
        served: Any = skill
        assert [s.do for s in served.program.steps] == [s["do"] for s in STEPS]
        assert served.program.steps[0].check.by == "rule" and set(served.program.exit) == {"escalate"}

    pin: dict[str, Any] = {
        "skillId": "sk_old",
        "version": 1,
        "name": "Hardship request triage",
        "slug": "hardship-request-triage",
        "useWhen": "The customer cannot pay because of a hardship.",
        "loading": "on_match",
        "instructions": "Steps: record the reason, offer the hardship form.",
    }
    old = definition_of("ag_old", 1, {"name": "Old", "role": "Helps", "instructions": "Help.", "skillPins": [pin]})
    (plain,) = load_catalog(SEED).settings_for(old, "m").skills
    loaded: Any = plain
    assert loaded.instructions == pin["instructions"] and loaded.program is None


async def test_a_step_naming_a_tool_the_team_no_longer_offers_blocks_the_publish_and_says_which_step(
    tmp_path: Path,
) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        rt = cast(Any, c)._transport.app.state.runtime
        directory = Directory(CatalogTools(rt.catalog), withdrawn=set())
        rt.tool_directory = directory
        steps = [
            {"do": "Look up the customer.", "use": LOOKUP},
            {"do": "Tell the person the amount."},
            {"do": "Ask them to confirm."},
            {"do": "Ask for the receipt.", "use": {"kind": "tool", "id": "request_document"}},
        ]
        body = {**REFUND, "toolIds": ["lookup_customer", "request_document"], "steps": steps}
        sid = _ok(await c.post("/v1/skills", json=body), 201)["id"]
        # This read fills the tools list the service keeps for 30 seconds, while the tool is still offered.
        check = _ok(await c.get(f"/v1/skills/{sid}"))["publishCheck"]
        assert (check["canRequest"], check["problems"], check["blockers"]) == (True, [], [])

        directory.withdrawn.add("request_document")
        error = _error(await c.post(f"/v1/skills/{sid}/publish-requests", json={"note": ""}))
        assert error["code"] == "cannot_request", error
        (problem,) = error["details"]["problems"]
        assert (problem["kind"], problem["id"], problem["position"]["step"]) == (
            "missing_reference",
            "tool:request_document",
            4,
        ), problem

        # The tools service cannot answer: nothing can be checked, so the publish is refused with that one problem.
        directory.withdrawn.clear()
        directory.down = True
        error = _error(await c.post(f"/v1/skills/{sid}/publish-requests", json={"note": ""}))
        assert [p["kind"] for p in error["details"]["problems"]] == ["unavailable_reference"], error
        assert _ok(await c.get(f"/v1/skills/{sid}"))["publishedVersion"] is None
