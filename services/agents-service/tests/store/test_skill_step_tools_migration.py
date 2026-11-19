"""Migration 0120 stores the tool of each skill step that named it only in its sentence, by failure mode: a skill
version or an agent version's pinned copy keeps a step whose tool is no longer the step's tool, in any tenant; a
step that names two tools or none, or already stores one, is rewritten; the digest no longer matches the body the
store digests; the tables are left without their forced row policy; a second run changes a row."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from alembic import command
from alembic.config import Config

from ops_agents.store.agent_registry import digest_of
from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0119_unattributed_side_tables"
SKILL = (
    "INSERT INTO registry_skills (tenant_id, id, slug, owner_team, team_id, origin, version, created_at, updated_at, "
    "updated_by) VALUES (:t, :s, :s, 'team_ops', 'team_ops', 'authored', 1, :at, :at, 'a@x')"
)
SKILL_VERSION = (
    "INSERT INTO registry_skill_versions (tenant_id, skill_id, version, content, digest, tokens, note, changes, "
    "saved_at, saved_by) VALUES (:t, :s, 1, CAST(:c AS json), 'old', 10, '', CAST('[]' AS json), :at, 'a@x')"
)
AGENT = (
    "INSERT INTO registry_agents (tenant_id, id, slug, team_id, version, paused, created_at, updated_at) "
    "VALUES (:t, :a, :a, 'team_ops', 1, false, :at, :at)"
)
AGENT_VERSION = (
    "INSERT INTO registry_agent_versions (tenant_id, agent_id, version, spec, digest, note, changes, saved_at, "
    "saved_by) VALUES (:t, :a, 1, CAST(:s AS json), 'old', '', CAST('[]' AS json), :at, 'a@x')"
)
FORCED = (
    "SELECT relname, relforcerowsecurity FROM pg_class "
    "WHERE relname IN ('registry_skill_versions', 'registry_agent_versions') ORDER BY relname"
)

ONE_TOOL = {"do": "Look up the account with @tool:get_account and @skill:kyc", "check": {"text": "Found"}}
TWO_TOOLS = {"do": "Compare @tool:get_account with @tool:get_ledger"}
NONE_NAMED = {"do": "Say hello", "use": None}
STORED = {"do": "Send it with @tool:send_mail", "use": {"kind": "tool", "id": "draft_mail"}}
ONE_WORKFLOW = {"do": "Open a case through @workflow:open_case, then @workflow:open_case again", "use": None}


def _rows(url: str, skills: list[str], agent: str) -> tuple[list[Any], list[Any]]:
    found = asyncio.run(
        _sql(
            url,
            (
                "SELECT skill_id, content, digest FROM registry_skill_versions WHERE skill_id IN (:a, :b) "
                "ORDER BY skill_id",
                {"a": skills[0], "b": skills[1]},
            ),
            ("SELECT spec, digest FROM registry_agent_versions WHERE agent_id = :a", {"a": agent}),
        )
    )
    return found[0], found[1]


def test_steps_naming_one_tool_store_it_in_every_tenant_and_a_second_run_changes_nothing(
    emptied_database: str,
) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    one, other, at = new_id("ten"), new_id("ten"), now_iso()
    mine, theirs, agent = new_id("skl"), new_id("skl"), new_id("agt")
    content = {"name": "Account", "steps": [ONE_TOOL, TWO_TOOLS, NONE_NAMED, STORED], "tokens": 3}
    spec = {
        "name": "Desk",
        "skillPins": [
            {"skillId": theirs, "version": 1, "steps": [ONE_WORKFLOW]},
            {"skillId": mine, "version": 1, "instructions": "No steps"},
        ],
    }
    asyncio.run(
        _sql(
            emptied_database,
            (SKILL, {"t": one, "s": mine, "at": at}),
            (SKILL_VERSION, {"t": one, "s": mine, "c": json.dumps(content), "at": at}),
            (SKILL, {"t": other, "s": theirs, "at": at}),
            (SKILL_VERSION, {"t": other, "s": theirs, "c": json.dumps({"steps": [ONE_WORKFLOW]}), "at": at}),
            (AGENT, {"t": other, "a": agent, "at": at}),
            (AGENT_VERSION, {"t": other, "a": agent, "s": json.dumps(spec), "at": at}),
        )
    )
    command.upgrade(cfg, "head")
    skills, agents = _rows(emptied_database, sorted([mine, theirs]), agent)
    by_id = {r[0]: (r[1], r[2]) for r in skills}
    filled, filled_digest = by_id[mine]
    assert filled["steps"] == [
        {**ONE_TOOL, "use": {"kind": "tool", "id": "get_account"}},
        TWO_TOOLS,
        NONE_NAMED,
        STORED,
    ]
    assert list(filled["steps"][0]) == ["do", "check", "use"], "a rewritten step keeps its keys in order"
    assert filled_digest == digest_of(filled)
    workflow = {**ONE_WORKFLOW, "use": {"kind": "workflow", "id": "open_case"}}
    assert by_id[theirs][0] == {"steps": [workflow]}, "another tenant's version is filled too"
    ((pinned, pinned_digest),) = agents
    assert pinned["skillPins"][0]["steps"] == [workflow]
    assert pinned["skillPins"][1] == spec["skillPins"][1]
    assert pinned_digest == digest_of(pinned)
    (forced,) = asyncio.run(_sql(emptied_database, (FORCED, {})))
    assert forced == [("registry_agent_versions", True), ("registry_skill_versions", True)]
    command.downgrade(cfg, BEFORE)
    command.upgrade(cfg, "head")
    assert _rows(emptied_database, sorted([mine, theirs]), agent) == (skills, agents)
    asyncio.run(
        _sql(
            emptied_database,
            ("DELETE FROM registry_agents WHERE id = :a", {"a": agent}),
            ("DELETE FROM registry_skills WHERE id IN (:a, :b)", {"a": mine, "b": theirs}),
        )
    )
