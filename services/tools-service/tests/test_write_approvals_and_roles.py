"""Write approvals: what makes a write wait and who approves their own, by failure mode:

- a write nobody turned approval on for runs without a token;
- an app set to ask a reviewer (appChangesByApp) holds its writes for a token;
- an app set to don't ask runs its write where the team asks a reviewer, and a team policy that cannot be read refuses
  the write (approval_rules_unavailable);
- a person approves their own write only while they hold Approvals decide in the team (Admin only by default), and
  one who does not is never let through (an imported write starts waiting, test_import).

Decided by the real Rego in OPA, on a seeded tenant's registry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access import Access, EffectiveAnswer
from ops_identity import Principal, dev_service_signer, mint_service_token
from ops_policy import mint
from ops_tools.modules.policy import WriteApprovals, approves_own_writes
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client
from .test_write_approval_gateway import Call, _gateway, reasons  # pyright: ignore[reportPrivateUsage]

CASE = {"subject": "Card stopped working abroad"}


def _module_of(modules: Sequence[Mapping[str, Any]], tool: str) -> str:
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


async def test_an_unreadable_team_policy_refuses_a_write(unreadable: Call) -> None:
    r = await unreadable("open_case", CASE, "quiet-2")
    assert (r.status_code, r.json()["error"]["code"]) == (503, "approval_rules_unavailable"), r.text


class TeamAsksPerson(WriteApprovals):
    """A team whose switch is on and answered by the person in the chat, recording what the gateway asked for."""

    def __init__(self) -> None:
        super().__init__(cast(Any, None))
        self.asked: list[tuple[str, str]] = []

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        return {"ask": True, "answer": "person", "reviewerRole": None}, {}

    async def answer(self, *args: Any, **kwargs: Any) -> EffectiveAnswer:
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


def _person(role: str) -> Principal:
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
    )


def test_only_a_person_holding_approvals_decide_approves_their_own_write() -> None:
    access = Access(security_team="team_security")
    assert approves_own_writes(access, _person("admin")), "an Admin holds Approvals decide by default"
    # A Reviewer decides the team's reviews but not their own request: someone else decides a reviewer's write.
    assert not approves_own_writes(access, _person("reviewer"))
    assert not approves_own_writes(access, _person("viewer")), "a viewer is asked like anyone else"


class OneTeamAsks(WriteApprovals):
    """Only `team` asks a reviewer; any other team, or none, asks nobody. Records the teams the gateway read."""

    def __init__(self, team: str) -> None:
        super().__init__(cast(Any, None))
        self.team = team
        self.read: list[str | None] = []

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        self.read.append(team_id)
        return (ASKS_REVIEWER if team_id == self.team else {}), {}


async def test_the_approval_rules_are_read_for_the_asking_team(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    """agents-service's token for a run names the run's team, and the person the run acts for must ask from that same
    team (or the token is refused). The rules are read for that team, never for the app's team or for none, which here
    would let the write run unapproved."""
    asking = "team_lending"
    service = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, team_id=asking
    )
    claims = {
        "sub": "usr_dana", "email": "dana@bank.test", "name": "Dana", "tenant_id": tenant, "team_id": asking,
        "kind": "acting_for", "act": {"sub": "service:agents"}, "aud": "tools",
    }  # fmt: skip
    headers = {"Authorization": f"Bearer {service}", "X-Acting-For": mint(claims, dev_service_signer(), ttl_s=600)}
    rules = OneTeamAsks(asking)
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa, write_approvals=rules)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as client,
        ):
            body = {"tool": "open_case", "input": CASE, "key": "asking-team-1", "runContext": {"act": "test"}}
            r = await client.post("/v1/calls", json=body, headers=headers)
    assert (r.status_code, reasons(r)) == (403, ["write needs an approval token"]), (r.text, rules.read)
