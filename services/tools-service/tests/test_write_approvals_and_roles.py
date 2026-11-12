"""Write approvals: what makes a write wait and who approves their own, by failure mode:

- a write nobody turned approval on for runs without a token;
- an app set to ask a reviewer (appChangesByApp) holds its writes for a token;
- an app set to don't ask runs its write where the team asks a reviewer, and a team policy that cannot be read makes
  the write wait;
- a person who decides the team's reviews approves their own write only while requesterMayDecide is on (off by
  default), and one who does not is never let through (an imported write starts waiting, test_import).

Decided by the real Rego in OPA, on a seeded tenant's registry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access import Access
from ops_identity import Principal
from ops_tools.modules.policy import WriteApprovals, approves_own_writes
from ops_tools.store.modules import ModuleStore

from .test_write_approval_gateway import Call, _gateway, reasons  # pyright: ignore[reportPrivateUsage]

CASE = {"subject": "Card stopped working abroad"}


def _module_of(modules: list[dict[str, Any]], tool: str) -> str:
    return next(f"module:{m['id']}" for m in modules if any(o["name"] == tool for o in m["operations"]))


class AppAnswers(WriteApprovals):
    """The team's levels as the live read answers them: `team` (None: unreadable) and one app's entry, the app holding
    `tool`. The team asks a reviewer when `team_asks` is set."""

    def __init__(self, engine: AsyncEngine, tool: str, app: dict[str, Any] | None, *, team: Any = None) -> None:
        super().__init__(cast(Any, None))
        self.engine = engine
        self.tool = tool
        self.app = app
        self.team = team

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        mods = await ModuleStore(self.engine).all_teams(tenant_id)
        return self.team, ({_module_of(mods, self.tool): self.app} if self.app else {})


ASKS_REVIEWER = {"ask": True, "answer": "reviewer", "reviewerRole": None}


@pytest.fixture
async def quiet(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(
        engine, seed, tenant, catalog_tools, AppAnswers(engine, "open_case", {"answer": "none"}, team=ASKS_REVIEWER)
    ):
        yield call


@pytest.fixture
async def unreadable(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, AppAnswers(engine, "open_case", None, team=None)):
        yield call


@pytest.fixture
async def gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, None):
        yield call


@pytest.fixture
async def listed(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(
        engine, seed, tenant, catalog_tools, AppAnswers(engine, "open_case", {"answer": "reviewer"}, team={})
    ):
        yield call


async def test_a_write_nobody_turned_approval_on_for_runs_without_a_token(gateway: Call) -> None:
    """open_case's switch is off, and the team set no policy: it runs."""
    r = await gateway("open_case", CASE, "off-1")
    assert r.status_code == 200 and r.json()["data"]["decision"] == "allow", r.text


async def test_a_listed_apps_write_waits_for_a_token(listed: Call) -> None:
    r = await listed("open_case", CASE, "off-2")
    assert (r.status_code, reasons(r)) == (403, ["write needs an approval token"]), r.text


async def test_an_app_set_to_dont_ask_runs_its_write_where_the_team_asks_a_reviewer(quiet: Call) -> None:
    r = await quiet("open_case", CASE, "quiet-1")
    assert r.status_code == 200 and r.json()["data"]["decision"] == "allow", r.text


async def test_an_unreadable_team_policy_makes_a_write_with_no_setting_wait(unreadable: Call) -> None:
    r = await unreadable("open_case", CASE, "quiet-2")
    assert (r.status_code, reasons(r)) == (403, ["write needs an approval token"]), r.text


class TeamAsksPerson(WriteApprovals):
    """A team whose switch is on and answered by the person in the chat, recording what the gateway asked for."""

    def __init__(self) -> None:
        super().__init__(cast(Any, None))
        self.asked: list[tuple[str, str]] = []

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        return {"ask": True, "answer": "person", "reviewerRole": None}, {}

    async def answer(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        got = await super().answer(*args, **kwargs)
        self.asked.append((kwargs["channel"], got["answer"]))
        return got


async def test_a_workflows_write_is_asked_as_a_workflow_and_goes_to_a_reviewer_where_the_team_asks_the_person(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    """A call acting for nobody (a workflow step) has no chat to confirm in: it must reach the resolver as a workflow,
    or "ask the person" holds it for an answer nobody can give."""
    team = TeamAsksPerson()
    async for call in _gateway(engine, seed, tenant, catalog_tools, team):
        r = await call("open_case", CASE, "wf-1")
        assert (r.status_code, reasons(r)) == (403, ["write needs an approval token"]), r.text
    assert team.asked == [("workflow", "reviewer")], team.asked


def _person(role: str, policies: dict[str, Any] | None = None) -> Principal:
    return Principal(
        kind="person",
        sub="usr_x",
        email="x@bank.example",
        name="X",
        tenant_id="t",
        team_id="team_ops",
        team_ids=["team_ops"],
        roles={"team_ops": role},
        scopes=[],
        auth_method="session",
        policies=policies or {},
    )


def test_only_a_person_who_decides_the_teams_reviews_approves_their_own_write() -> None:
    access = Access(security_team="team_security")
    loose = {"requesterMayDecide": True}
    assert approves_own_writes(access, _person("admin", loose)) and approves_own_writes(
        access, _person("approver", loose)
    )
    assert not approves_own_writes(access, _person("viewer", loose)), "a viewer is asked like anyone else"
    # The four-eyes rule, the default: someone else decides even an admin's write.
    assert not approves_own_writes(access, _person("admin"))
