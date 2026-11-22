"""The Workspace app's tools run for an agent's call (draft_agent, invite_people), by failure mode: a call with no
person behind it runs on the calling service's rights, a person's call carries cells their role does not give them,
and the person's proof is sent to a service other than the one it was minted for. The owning services are faked at
the HTTP edge; the runner and the platform tools list are the real ones."""

from __future__ import annotations

from typing import Any

import httpx

from ops_access.catalogue import Grant, encode_grid
from ops_identity import ActingForPerson, ActingForTokens, dev_service_signer
from ops_policy import verify
from ops_tools.mcp_tools import PlatformTools
from ops_tools.tools import LocalToolRunner, ToolCaller

TENANT, TEAM = "ten_ws", "team_lending"


def person(role: str, cells: list[Grant], team: str = TEAM) -> ActingForPerson:
    return ActingForPerson(
        sub="usr_ana",
        email="ana@bank.test",
        name="Ana",
        team_id=team,
        access={"roles": {team: role}, "access": {team: [role]}, "grids": {role: encode_grid(cells)}},
    )


def caller(acting: ActingForPerson | None) -> ToolCaller:
    return ToolCaller(tenant_id=TENANT, team_id=TEAM, sub="service:agents", kind="service", acting_for=acting)


class Upstream:
    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        return httpx.Response(200, json={"success": True, "data": {"id": "made"}})


def runner(up: Upstream) -> LocalToolRunner:
    signer = dev_service_signer()
    people = {s: ActingForTokens.for_dev(signer, service="tools", audience=s) for s in ("agents", "platform")}
    http = httpx.AsyncClient(transport=httpx.MockTransport(up.handler))
    tools = PlatformTools({"agents": "http://agents", "platform": "http://platform"}, signer, http, people=people)
    return LocalToolRunner([], workspace=tools)  # pyright: ignore[reportArgumentType]


def scopes(r: httpx.Request, audience: str = "agents") -> list[Any]:
    token = r.headers["Authorization"].removeprefix("Bearer ")
    return list(verify(token, dev_service_signer().verifier(audience)).get("scopes") or [])


def claims_of(token: str, audience: str) -> dict[str, Any]:
    return dict(verify(token, dev_service_signer().verifier(audience)))


async def test_a_workspace_tool_with_no_person_or_another_team_runs_nothing() -> None:
    up = Upstream()
    for acting in (None, person("admin", [("agents", "create", "all")], team="team_other")):
        out = await runner(up).run("draft_agent", {"name": "Policy", "role": "Answers"}, key="k", caller=caller(acting))
        assert not out.ok and out.output["error"]["code"] == "acting_for_required", out
    assert up.sent == []


async def test_a_viewers_draft_carries_no_create_cell_and_a_builders_does() -> None:
    up = Upstream()
    args = {"name": "Policy helper", "role": "Answers from the lending policy"}
    await runner(up).run("draft_agent", args, key="k1", caller=caller(person("viewer", [("agents", "view", "all")])))
    await runner(up).run("draft_agent", args, key="k2", caller=caller(person("builder", [("agents", "create", "all")])))
    viewer, builder = up.sent
    assert str(viewer.url) == "http://agents/v1/agents" and scopes(viewer) == [], viewer.headers
    assert scopes(builder) == ["agents:create"]
    assert claims_of(builder.headers["X-Acting-For"], "agents")["email"] == "ana@bank.test"


async def test_an_invite_goes_to_platform_with_a_proof_for_platform_only() -> None:
    up = Upstream()
    admin = person("admin", [("access", "create", "all")])
    out = await runner(up).run(
        "invite_people", {"emails": ["sam@bank.test"], "role": "viewer"}, key="k", caller=caller(admin)
    )
    assert out.ok, out
    (sent,) = up.sent
    assert str(sent.url) == "http://platform/v1/settings/members/invite" and scopes(sent, "platform") == [
        "access:create"
    ]
    proof = sent.headers["X-Acting-For"]
    assert claims_of(proof, "platform")["sub"] == "dev:ana@bank.test"
