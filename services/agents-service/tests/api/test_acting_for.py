"""Whom agents-service's tool calls act for, by failure mode: a run's call acts for nobody or the wrong person
(a child run, a run an API key started), a chat turn's call loses its person, the token never reaches tools-service, a
platform-service outage fails every personal call at once, and an acting-for token signs a person in here."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from ops_agents.activities.gateway import GatewayClient, GatewayRefused, RunContext
from ops_agents.api import runs
from ops_agents.api.acting_for import CallPeople
from ops_agents.api.auth import Principal
from ops_agents.api.child_runs import _started_by, acting_for
from ops_agents.api.run_person import running_for
from ops_identity import ACTING_FOR_HEADER, ActingForTokens, ServiceClient, dev_service_signer
from ops_policy import mint, verify
from ops_service_kit.errors import Forbidden, ServiceUnavailable
from ops_store import isolation
from tests.api import test_platform_identity
from tests.api.test_platform_identity import PLATFORM

RUNS = {
    "wfrun_top": {"id": "wfrun_top", "team_id": "team_a", "created_by": "j.richardson@bank.test"},
    "wfrun_child": {"id": "wfrun_child", "team_id": "team_a", "created_by": "run:wfrun_top"},
    "wfrun_key": {"id": "wfrun_key", "team_id": "team_a", "created_by": "key:key_abc"},
    "wfrun_mail": {"id": "wfrun_mail", "team_id": "team_a", "created_by": "mailbox:claims"},
}


class Runs:
    async def get(self, run_id: str) -> dict[str, Any] | None:
        return RUNS.get(run_id)


class Minted:
    """A stand-in for platform-service: records whom it minted for; fails while `down`."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.down = False

    async def __call__(self, tenant_id: str, email: str, team_id: str) -> tuple[str, float]:
        if self.down:
            raise httpx.ConnectError("platform-service is down")
        self.asked.append(email)
        return f"token-for-{email}", 1000.0


def people(minted: Minted, clock: list[float] | None = None) -> CallPeople:
    now = clock or [0.0]
    return CallPeople(ActingForTokens(minted, clock=lambda: now[0]), Runs)


async def test_a_runs_calls_act_for_its_starter_and_a_child_runs_for_its_parents_starter() -> None:
    who = people(Minted())
    assert await who.email(RunContext(thread=None, run_id="wfrun_top")) == "j.richardson@bank.test"
    assert await who.email(RunContext(thread=None, run_id="wfrun_child")) == "j.richardson@bank.test"


async def test_a_run_an_agent_started_from_chat_acts_for_the_person_who_asked() -> None:
    # The starter is written by the path a chat's workflow tool takes, so the reader is held to the writer's format.
    person = Principal(tenant_id="ten_a", sub="usr_maya", email="m.okafor@bank.test", name="Maya", team_id="team_a")
    with acting_for(person):
        started_by = _started_by({"agentId": "agt_case_desk"})
    RUNS["wfrun_agent"] = {"id": "wfrun_agent", "team_id": "team_a", "created_by": started_by}
    RUNS["wfrun_agent_child"] = {"id": "wfrun_agent_child", "team_id": "team_a", "created_by": "run:wfrun_agent"}
    minted = Minted()
    who = people(minted)
    for run in ("wfrun_agent", "wfrun_agent_child"):
        ctx = RunContext(thread=None, run_id=run)
        assert await who.headers(ctx, tenant_id="ten_a", team_id="team_a") == {
            ACTING_FOR_HEADER: "token-for-m.okafor@bank.test"
        }
    assert minted.asked == ["m.okafor@bank.test"]


async def test_a_run_an_api_key_or_a_mailbox_started_acts_for_nobody() -> None:
    minted = Minted()
    who = people(minted)
    for run in ("wfrun_key", "wfrun_mail"):
        ctx = RunContext(thread=None, run_id=run)
        assert await who.headers(ctx, tenant_id="ten_a", team_id="team_a") == {}
    assert minted.asked == []


async def test_a_chat_turns_call_acts_for_the_person_chatting() -> None:
    person = Principal(tenant_id="ten_a", sub="usr_maya", email="m.okafor@bank.test", name="Maya", team_id="team_a")
    with acting_for(person):
        assert await people(Minted()).email(RunContext(thread=None, run_id="wfrun_top")) == "m.okafor@bank.test"


async def test_a_failed_mint_serves_the_cached_token_until_it_expires_then_says_try_again() -> None:
    minted, clock = Minted(), [0.0]
    who = people(minted, clock)
    ctx = RunContext(thread=None, run_id="wfrun_top")
    first = await who.headers(ctx, tenant_id="ten_a", team_id="team_a")
    minted.down = True
    clock[0] = 995.0  # inside the renewal window: a mint is tried, fails, and the cached token still serves
    assert await who.headers(ctx, tenant_id="ten_a", team_id="team_a") == first
    clock[0] = 1001.0
    with pytest.raises(ServiceUnavailable) as e:
        await who.headers(ctx, tenant_id="ten_a", team_id="team_a")
    assert e.value.code == "acting_for_unavailable"


async def test_a_refused_mint_is_not_served_from_the_cache() -> None:
    async def refuse(tenant_id: str, email: str, team_id: str) -> tuple[str, float]:
        raise Forbidden("not a member", code="acting_for_refused")

    who = CallPeople(ActingForTokens(refuse), Runs)
    with pytest.raises(Forbidden):
        await who.headers(RunContext(thread=None, run_id="wfrun_top"), tenant_id="ten_a", team_id="team_a")


async def test_the_gateway_call_carries_the_token_to_tools_service() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True, "data": {"ok": True, "output": {}}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://tools")
    tools = ServiceClient(http, dev_service_signer(), "agents", "tools", tenant=lambda: "ten_a", team=lambda: "team_a")
    gateway = GatewayClient(tools)
    gateway.people = CallPeople(ActingForTokens.for_dev(dev_service_signer(), service="agents"), Runs)
    person = Principal(tenant_id="ten_a", sub="usr_maya", email="m.okafor@bank.test", name="Maya", team_id="team_a")
    with acting_for(person):
        await gateway.call("lookup", {}, key="k1", approval_token=None)
    claims = verify(seen[0].headers[ACTING_FOR_HEADER], dev_service_signer().verifier("tools"))
    assert (claims["email"], claims["team_id"], claims["act"]) == (
        "m.okafor@bank.test",
        "team_a",
        {"sub": "service:agents"},
    )


# The platform-mode app of test_platform_identity, people verified against its key set.
client = test_platform_identity.client


async def test_an_acting_for_token_does_not_sign_a_person_in(client: AsyncClient) -> None:
    claims = {
        "sub": "usr_james",
        "email": "j.richardson@bank.test",
        "tenant_id": "acme",
        "team_id": "team_a",
        "team_ids": ["team_a"],
        "kind": "acting_for",
        "act": {"sub": "service:agents"},
        "aud": ["agents"],
    }
    headers = {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=60)}", "X-Team-Id": "team_a"}
    assert (await client.get("/v1/threads", headers=headers)).status_code == 401


async def test_a_recovered_chat_run_acts_for_the_threads_person_and_one_with_no_person_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A chat turn cut off by a restart was recovered with no person, and its Salesforce reads ran as the team account.
    minted = Minted()
    who = people(minted)
    seen: list[object] = []

    async def graph_run(rt: object, row: dict[str, Any], graph: object, **_: Any) -> Any:
        try:
            seen.append(
                await who.headers(RunContext(thread=row["id"], run_id="run_rec"), tenant_id="ten_a", team_id="team_a")
            )
        except GatewayRefused as e:
            seen.append(e.code)
        yield {"event": "step"}

    monkeypatch.setattr(runs, "_execute", graph_run)
    rt = SimpleNamespace(
        graph_store=SimpleNamespace(engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    )
    chat = {
        "id": "th_1",
        "team_id": "team_a",
        "graph": "agent_wrapper",
        "meta": {"ownerEmail": "j.richardson@bank.test"},
    }
    nobody = {**chat, "id": "th_2", "meta": {}}
    workflow: dict[str, Any] = {"id": "th_3", "team_id": "team_a", "graph": "complex_workflow", "meta": {}}
    for row in (chat, nobody, workflow):
        with isolation.scope("ten_a", None):
            async for _ in runs.execute(rt, row, None, graph_input=None, run_id="run_rec", kind="recovery"):  # type: ignore[arg-type]
                pass
    assert seen == [{ACTING_FOR_HEADER: "token-for-j.richardson@bank.test"}, "no_person", {}], seen
    assert minted.asked == ["j.richardson@bank.test"]


async def test_a_chat_run_resumed_by_someone_else_still_acts_for_the_person_who_asked() -> None:
    # An approver's decision resumed the chat's write as the approver.
    who = people(Minted())
    chat = {
        "id": "th_1",
        "team_id": "team_a",
        "graph": "agent_wrapper",
        "meta": {"ownerEmail": "j.richardson@bank.test"},
    }
    approver = Principal(name="Maya", email="m.okafor@bank.test", team_id="team_a", tenant_id="ten_a", sub="u2")
    with acting_for(approver), running_for(chat):
        assert await who.email(RunContext(thread="th_1", run_id="run_resume")) == "j.richardson@bank.test"
