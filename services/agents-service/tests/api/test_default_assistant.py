"""Each team's Ops Assistant is a team default agents-service provisions, by failure mode: a new team's
assistant cannot read its knowledge or files; an assistant made before a newer declaration keeps the old one after a
restart; and one a person changed is overwritten."""

from __future__ import annotations

from ops_agents.activities.catalog import AgentDefinition
from ops_agents.api.agent_registry import go_live, registry, spec_from_seed
from ops_agents.api.deps import Runtime
from ops_agents.api.ops_tools import (
    BUILT_IN_READS,
    OPS_ASSISTANT,
    SYSTEM,
    catch_up_assistants,
    ops_assistant_id,
)
from ops_agents.store.team_defaults import TeamDefaults
from ops_agents.store.tenancy import tenant_scope
from ops_identity import dev_service_signer, mint_service_token
from tests.api.test_action_roles import VIEWER
from tests.api.test_team_default_agent import Stack, stack, start  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import TENANT

TEAM = "team_ops"
AID = ops_assistant_id(TEAM)


async def made_before(rt: Runtime) -> None:
    """The team's assistant as the first declaration made it: no built-in reads granted."""
    old = AgentDefinition.model_validate({**OPS_ASSISTANT, "id": AID, "version": 1, "tools": []})
    spec = spec_from_seed(old, rt.settings.model_alias)
    with tenant_scope(TENANT):
        assert await registry(rt).create_if_absent(spec, by=SYSTEM, team_id=TEAM, agent_id=AID)
        go_live(rt, AID, 1, spec)
        await TeamDefaults(rt.db).set_agent(TEAM, AID, by=SYSTEM)


async def test_a_teams_first_chat_gets_an_assistant_granted_the_built_in_reads(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    assert (await start(c, VIEWER))["agentId"] == AID
    live = rt.catalog.agent(AID)
    assert live is not None and set(BUILT_IN_READS) <= set(live.tools), live
    assert live.model_alias == "assistant", live.model_alias


async def test_a_restart_brings_an_older_assistant_to_the_declared_one(stack: Stack) -> None:  # noqa: F811
    _, rt = stack
    await made_before(rt)
    assert await catch_up_assistants(rt) == 1
    live = rt.catalog.agent(AID)
    assert live is not None and set(BUILT_IN_READS) <= set(live.tools), live


async def test_a_restart_brings_an_older_assistant_its_new_prompt_and_tool_cap(stack: Stack) -> None:  # noqa: F811
    # An assistant made with the old prompt kept its cap of four: only the instructions and tools followed the seed.
    _, rt = stack
    old = AgentDefinition.model_validate(
        {**OPS_ASSISTANT, "id": AID, "version": 1, "max_tool_calls": 4, "model_alias": None}
    )
    spec = spec_from_seed(old.model_copy(update={"instructions": old.instructions[:1]}), rt.settings.model_alias)
    with tenant_scope(TENANT):
        assert await registry(rt).create_if_absent(spec, by=SYSTEM, team_id=TEAM, agent_id=AID)
        go_live(rt, AID, 1, spec)
        await TeamDefaults(rt.db).set_agent(TEAM, AID, by=SYSTEM)
    await catch_up_assistants(rt)
    live = rt.catalog.agent(AID)
    assert live is not None and live.max_tool_calls == OPS_ASSISTANT["max_tool_calls"], live
    # It ran on the runtime's alias with every other agent; it moves to its own.
    assert spec["model"] == rt.settings.model_alias and live.model_alias == "assistant", live.model_alias
    assert [f.text for f in live.instructions] == [f["text"] for f in OPS_ASSISTANT["instructions"]]


async def test_an_assistant_a_person_changed_is_left_as_it_is(stack: Stack) -> None:  # noqa: F811
    _, rt = stack
    await made_before(rt)
    with tenant_scope(TENANT):
        reg = registry(rt)
        spec = dict((await reg.version(AID, 1))["spec"])
        n = await reg.save(AID, {**spec, "role": "Our desk helper"}, by="priya@harborpine.example")
        await reg.publish(AID, n, by="priya@harborpine.example", review_id="test")
        go_live(rt, AID, n, {**spec, "role": "Our desk helper"})
    await catch_up_assistants(rt)
    live = rt.catalog.agent(AID)
    assert live is not None and live.role == "Our desk helper" and not set(BUILT_IN_READS) & set(live.tools), live


def platform_token(team: str, scopes: list[str]) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="platform", audience="agents", tenant_id=TENANT, scopes=scopes, team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


async def test_a_new_team_gets_its_assistant_from_the_team_created_event(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    body = {"name": "team.created", "key": "team_new", "teamId": "team_new"}
    refused = await c.post("/v1/platform-events", json=body, headers=platform_token("team_new", []))
    assert refused.status_code == 403, refused.text
    done = await c.post("/v1/platform-events", json=body, headers=platform_token("team_new", ["agents:create"]))
    assert done.status_code == 200 and done.json()["data"]["changed"] == 1, done.text
    again = await c.post("/v1/platform-events", json=body, headers=platform_token("team_new", ["agents:create"]))
    assert again.json()["data"]["changed"] == 0, again.text
    live = rt.catalog.agent(ops_assistant_id("team_new"))
    assert live is not None and set(BUILT_IN_READS) <= set(live.tools), live
    with tenant_scope(TENANT):
        assert await TeamDefaults(rt.db).agent("team_new") == ops_assistant_id("team_new")
