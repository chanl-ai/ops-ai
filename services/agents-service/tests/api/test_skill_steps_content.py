"""A skill's steps through /v1/skills and the agent's pins, by failure mode: a save dropping the steps, exits,
results, not-when or success lines, storing a mistyped rule as a check the model judges, or saving a skill that cannot
run; a pin losing the steps, or a pin saved before steps no longer loading; a skill publishing while a step names a
tool the team no longer offers, or the refusal not saying which step; a step that changes something saved or
published with no rule behind it; and a tool a sentence only names being run as the step's tool, or a step that
names one tool and runs none publishing unseen.

Where the design names no shape, these tests fix one: a refused step answers its 1-based position as
`error.details.step`."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from httpx import AsyncClient

from ops_agent_kernel import steps
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tool_directory import CatalogTools
from ops_agents.api.agent_calls import AgentCalls
from ops_agents.api.agent_registry import definition_of
from ops_agents.app import skill_content
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


def _error(r: Any, status: int = 400) -> dict[str, Any]:
    assert r.status_code == status, r.text
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
            # A rule on a result needs the tool the result comes from, stored as the step's own: naming it in the
            # sentence is not enough.
            "check_needs_tool": {"steps": _step(1, use=None, do="Look up the customer and the charge.")},
        }
        two = "Look up the customer with @tool:lookup_customer."
        error = _error(await c.put(url, json={"steps": _step(1, use=None, do=two), "baseVersion": 1}))
        assert (error["code"], error["details"]["step"]) == ("check_needs_tool", 1), error
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


RECEIPT = {"kind": "tool", "id": "request_document"}
# A rule on the write's own result, and an ending when it does not hold: the default would offer the write again.
SENT: dict[str, Any] = {"check": {"text": "exists(result.id)"}, "ifNot": {"action": "exit", "exit": "failed"}}


async def test_a_step_that_changes_something_is_refused_without_a_rule_check(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        body = {**REFUND, "toolIds": ["lookup_customer", "request_document"]}
        ask = {"do": "Ask for the receipt.", "use": RECEIPT}
        for check in ({}, {"check": {"text": "The receipt was asked for."}}):
            error = _error(await c.post("/v1/skills", json={**body, "steps": [STEPS[0], {**ask, **check}]}))
            assert (error["code"], error["details"]["step"]) == ("write_needs_rule", 2), (check, error)
        # A read needs none, and the write with a rule on its result is saved.
        saved = _ok(
            await c.post("/v1/skills", json={**body, "steps": [{"do": "Look up.", "use": LOOKUP}, {**ask, **SENT}]}),
            201,
        )
        assert saved["publishCheck"]["canRequest"] is True, saved["publishCheck"]
        # A version stored before the rule cannot be published either.
        old: dict[str, Any] = {"steps": [{"do": "Look up.", "use": LOOKUP}, ask]}
        access = {"lookup_customer": "read", "request_document": "write"}
        problems, _ = await skill_content.publish_problems(old, access, team_id="Retail", skills=cast(Any, None))
        assert [(p["kind"], cast(Any, p["position"])["step"]) for p in problems] == [("bad_check", 2)], problems


async def test_a_tool_a_sentence_only_names_is_not_run_and_the_publish_check_says_so(tmp_path: Path) -> None:
    """A step runs the tool stored as its `use` and no other. Text sent by the SDK, the CLI or a paste can name a
    tool without marking it: read as the step's tool, "never use @tool:x here" would run x."""
    async with _app(str(tmp_path / "db.sqlite")) as c:
        steps = [
            {"do": "Look up the customer with @tool:lookup_customer."},
            {"do": "Read @tool:lookup_customer again before asking.", "use": RECEIPT, **SENT},
            {"do": "Use @tool:lookup_customer or @tool:request_document."},
            {"do": "Tell the person what happens next."},
        ]
        body = {**REFUND, "toolIds": ["lookup_customer", "request_document"], "steps": steps}
        saved = _ok(await c.post("/v1/skills", json=body), 201)
        program = skill_content.program_of(saved["content"])
        assert program is not None
        assert [s.use and s.use.id for s in program.steps] == [None, "request_document", None, None]
        check = saved["publishCheck"]
        assert check["canRequest"] is False
        assert [(p["kind"], p["id"], p["position"]["step"]) for p in check["problems"]] == [
            ("bad_step", "tool:lookup_customer", 1)
        ], check["problems"]
        assert sorted((w["id"], w["position"]["step"]) for w in check["warnings"]) == [
            ("tool:lookup_customer", 2),
            ("tool:lookup_customer", 3),
            ("tool:request_document", 3),
        ], check["warnings"]
        error = _error(await c.post(f"/v1/skills/{saved['id']}/publish-requests", json={"note": ""}))
        assert error["code"] == "cannot_request", error


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
            {"do": "Ask for the receipt.", "use": RECEIPT, **SENT},
        ]
        body = {**REFUND, "toolIds": ["lookup_customer", "request_document"], "steps": steps}
        sid = _ok(await c.post("/v1/skills", json=body), 201)["id"]
        # This read fills the tools list the service keeps for 30 seconds, while the tool is still offered.
        check = _ok(await c.get(f"/v1/skills/{sid}"))["publishCheck"]
        assert (check["canRequest"], check["problems"], check["blockers"], check["warnings"]) == (True, [], [], [])

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


async def test_a_step_that_asks_another_agent_is_locked_under_the_name_the_service_grants(tmp_path: Path) -> None:
    """A step asks another agent as `@agent:<id>`, the agent holds it as `agent:<id>`, and the model calls
    `agent__<id>`. Read under any other spelling, the kernel owns a tool nobody is granted and the hand-off stays
    free of its step."""
    async with _app(str(tmp_path / "db.sqlite")) as c:
        ask = {"do": "Ask the branch desk.", "use": {"kind": "agent", "id": BRANCH}}
        body = {**REFUND, "steps": [{"do": "Look up.", "use": LOOKUP}, ask]}
        # Another agent may change anything, whatever access its tool says: the step needs a rule like a write.
        error = _error(await c.post("/v1/skills", json=body))
        assert (error["code"], error["details"]["step"]) == ("write_needs_rule", 2), error
        ruled = {**ask, "check": {"text": "exists(result.answer)"}, "ifNot": {"action": "exit", "exit": "failed"}}
        saved = _ok(await c.post("/v1/skills", json={**body, "steps": [body["steps"][0], ruled]}), 201)
        program = skill_content.program_of(saved["content"])
        assert program is not None

    # The grant as the service builds it for a chat, and what the kernel then keeps for the step.
    granted = AgentCalls._grant(cast(Any, None), SimpleNamespace(id=BRANCH, name="Branch desk", role="desk"))  # pyright: ignore[reportPrivateUsage]
    skill = cast(Any, SimpleNamespace(program=program, slug="refund-a-charge"))
    access = {"lookup_customer": "read", granted.name: granted.access}
    assert steps.owned([skill], access) == {granted.name: ["refund-a-charge"]}


@dataclass
class Reclassified:
    """The fixture catalogue, with the tools in `writes` listed as ones that change something."""

    inner: CatalogTools
    writes: set[str]

    async def operations(self) -> list[Any]:
        return [replace(o, access="write") if o.name in self.writes else o for o in await self.inner.operations()]


async def test_a_published_skill_that_would_no_longer_save_is_not_attached_and_blocks_its_agents_publish(
    tmp_path: Path,
) -> None:
    """The step checks run when a skill is saved. A version published before one existed, or whose tool has since
    become a write, is still pinned and attached as it was: the agent's publish check and the attach read the same
    checks, or old versions run steps a new save would refuse."""
    async with _app(str(tmp_path / "db.sqlite")) as c:
        rt = cast(Any, c)._transport.app.state.runtime
        directory = Reclassified(CatalogTools(rt.catalog), writes=set())
        rt.tool_directory = directory
        body = {**REFUND, "steps": [{"do": "Look up the customer.", "use": LOOKUP}]}
        sid = await _published(c, body)
        added = _ok(await c.post(f"/v1/agents/{BRANCH}/references", json={"kind": "skill", "id": sid}))
        at = {"version": added["agentVersion"]}
        clear = _ok(await c.get(f"/v1/agents/{BRANCH}/publish-check", params=at))
        assert [p for p in clear["problems"] if p["position"]["field"] == "skills"] == [], clear

        # The look-up becomes a tool that changes something; the published version has no rule on that step.
        directory.writes.add("lookup_customer")
        check = _ok(await c.get(f"/v1/agents/{BRANCH}/publish-check", params=at))
        found = [(p["kind"], p["id"], p["position"]) for p in check["problems"]]
        assert found == [("bad_check", f"skill:{sid}", {"field": "skills", "step": 1, "index": None})], check
        assert check["canRequest"] is False
        refused = _error(await c.post(f"/v1/agents/{BRANCH}/publish-requests", json={**at, "note": ""}), 422)
        assert refused["code"] == "cannot_publish", refused
        other = _error(await c.post("/v1/agents/ag_dispute/references", json={"kind": "skill", "id": sid}), 422)
        assert other["code"] == "skill_needs_fix", other


async def test_an_attach_while_the_tools_list_cannot_be_read_fails_as_unavailable_not_as_a_skill_fault(
    tmp_path: Path,
) -> None:
    """With tools-service down no tool's access is known. Read as "every tool changes something", a skill whose step
    makes a plain look-up is refused for a missing rule, and its builder is sent to fix a skill that is fine."""
    async with _app(str(tmp_path / "db.sqlite")) as c:
        rt = cast(Any, c)._transport.app.state.runtime
        directory = Directory(CatalogTools(rt.catalog), withdrawn=set())
        rt.tool_directory = directory
        looks = await _published(c, {**REFUND, "steps": [{"do": "Look up the customer.", "use": LOOKUP}]})
        talks = await _published(c, {**REFUND, "name": "Greet", "toolIds": [], "steps": [{"do": "Say hello."}]})
        directory.down = True
        refused = await c.post(f"/v1/agents/{BRANCH}/references", json={"kind": "skill", "id": looks})
        assert refused.status_code == 503 and "skill_needs_fix" not in refused.text, refused.text
        # A skill whose steps run no tool needs nothing from the tools list.
        _ok(await c.post(f"/v1/agents/{BRANCH}/references", json={"kind": "skill", "id": talks}))
