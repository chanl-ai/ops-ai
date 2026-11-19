"""Permission decisions that go through the one central check, by failure mode: a person without the view right reads
a team's definitions anyway while a Chat user must still chat; a review that names a reviewer role refuses a membership
approver whose token has no access claim, or a workspace Admin holding the role in every team, and lets in a person
without the role."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from ops_agents.api import hitl_facade
from ops_agents.api.auth import Principal
from ops_identity import Principal as Caller
from ops_service_kit.errors import Forbidden
from tests.api.role_app import role_app
from tests.engine.test_lifecycle_rights import person

TEAM = "team_ops"
NO_SKILL_VIEW = person("sam", TEAM, "builder", unticked=(("skills", "view"),))
CHAT_USER = person("cleo", TEAM, "chat_user")


@pytest.fixture
async def client() -> Any:
    async with role_app(TestModel()) as c:
        yield c


async def test_a_person_without_the_view_right_lists_no_definitions_and_a_chat_user_still_chats(
    client: AsyncClient,
) -> None:
    refused = [await client.get("/v1/skills", headers=who) for who in (CHAT_USER, NO_SKILL_VIEW)]
    assert [r.status_code for r in refused] == [403, 403], [r.text[:120] for r in refused]
    assert {r.json()["error"]["code"] for r in refused} == {"forbidden"}
    chat = await client.get("/chat/agents", headers=CHAT_USER)
    assert chat.status_code == 200, chat.text


def decider(*, roles: dict[str, str], access: dict[str, list[str]]) -> Principal:
    identity = Caller(
        kind="person",
        sub="usr_maya",
        email="maya@harborpine.example",
        name="Maya",
        tenant_id="acme",
        team_id=TEAM,
        team_ids=[TEAM],
        roles=roles,
        scopes=[],
        auth_method="session",
        access=access,
    )
    return Principal(
        name="Maya",
        email=identity.email,
        team_id=TEAM,
        tenant_id="acme",
        sub=identity.sub,
        team_ids=(TEAM,),
        role=roles.get(TEAM),
        roles=roles,
        identity=identity,
    )


async def check(who: Principal) -> None:
    row = {"team_id": TEAM}
    await hitl_facade.check_thread_decider(None, who, row, {"reviewer_role": "reviewer"}, [])  # type: ignore[arg-type]


async def test_a_review_naming_the_reviewer_role_is_decided_by_who_holds_it_in_any_way_the_grid_records() -> None:
    # A token issued before roles were data carries the membership name `approver`; the review names the role id.
    await check(decider(roles={TEAM: "approver"}, access={}))
    # An Admin assignment in every team holds the reviewer cells in this one.
    await check(decider(roles={}, access={"*": ["admin"]}))
    # A custom role that decides reviews does not stand in for the named role.
    custom = decider(roles={}, access={TEAM: ["custom_decider"]})
    with pytest.raises(Forbidden) as refused:
        await check(custom)
    assert refused.value.code == "role_required"
