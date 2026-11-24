"""A tool access request's decision applied through the gateway, by failure mode: a team's own workflow, or
an agent, granting access with an approval its own review minted; a call with no approval at all; the decision
recorded under nobody, or the rejection's reason lost; a decision for a request another team decides; and a retried
run applying its decision twice, or reviving a request revoked meanwhile (the rules, now on this path)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ActingForPerson, ServiceUnreachable, dev_service_signer, mint_service_token, principal_of
from ops_policy import input_hash
from ops_policy.approval import Binding
from ops_policy.approval import mint_approval as mint
from ops_service_kit.errors import Forbidden
from ops_tools.modules.directory import Directory
from ops_tools.modules.policy import OwnRequests
from ops_tools.modules.service import ModuleService
from ops_tools.store import CallLog
from ops_tools.store.modules import ModuleStore

from .conftest import REVIEW_KEY, service_headers
from .test_calls import Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_module_roles import ACCESS, MODULES

TOOL = "apply_tool_access"
WORKFLOW = "tool_access_request"


async def apply_access(
    client: httpx.AsyncClient,
    tenant: str,
    approval: dict[str, Any],
    decision: str = "approved",
    *,
    reason: str | None = None,
    workflow: str = WORKFLOW,
    system: bool = True,
    token: bool = True,
    team: str | None = None,
    approvers: list[str] | None = None,
) -> httpx.Response:
    """The call the system workflow's apply step sends, with the token a decision in Human Tasks mints for it."""
    module_id = str(approval.get("moduleId") or "mod_core_banking")
    args: dict[str, Any] = {"moduleId": module_id, "approvalId": approval["id"], "decision": decision}
    if reason:
        args["reason"] = reason
    thread = f"wfrun_{uuid4().hex[:12]}"
    step = f"{thread}:grant:1:1"
    people = approvers or ["m.okafor@bank.example"]
    binding = Binding(thread, step, TOOL, input_hash(args), people, workflow=workflow, system=system)
    body = {
        "tool": TOOL,
        "input": args,
        "key": step,
        "runContext": {"thread": thread, "step": step, "act": f"workflow:{workflow}"},
        "approvalToken": mint(binding, REVIEW_KEY, ttl_s=300) if token else None,
    }
    # A run's call names the run's team in agents-service's token, as the worker sets it (worker.py set_team).
    headers = service_headers(tenant)
    if team:
        team_token = mint_service_token(
            dev_service_signer(),
            service="agents",
            audience="tools",
            tenant_id=tenant,
            team_id=team,
            scopes=["tools:view"],
        )
        headers = {"Authorization": f"Bearer {team_token}"}
    return await client.post("/v1/calls", json=body, headers=headers)


async def _ask(g: Gateway) -> dict[str, Any]:
    r = await g.client.post(f"{MODULES}/mod_core_banking/approvals", json=ACCESS)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _ask_other(g: Gateway) -> dict[str, Any]:
    r = await g.client.post(f"{MODULES}/mod_core_banking/approvals", json={**ACCESS, "workflowId": "wf_mortgage"})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _status(g: Gateway, approval: dict[str, Any]) -> dict[str, Any]:
    m = (await g.client.get(f"{MODULES}/mod_core_banking")).json()["data"]
    return next(a for a in m["approvals"] if a["id"] == approval["id"])


async def test_only_the_system_workflow_applies_a_decision(gateway: Gateway) -> None:  # noqa: F811
    approval = await _ask(gateway)
    own = await apply_access(gateway.client, gateway.tenant, approval, workflow="team_grants", system=False)
    assert (own.status_code, own.json()["error"]["code"]) == (403, "system_workflow_only"), own.text
    named = await apply_access(gateway.client, gateway.tenant, approval, system=False)
    assert named.status_code == 403, "a team workflow named like the system one is still not the system one"
    bare = await apply_access(gateway.client, gateway.tenant, approval, token=False)
    assert bare.status_code == 403, bare.text
    assert (await _status(gateway, approval))["status"] == "requested"
    ok = await apply_access(gateway.client, gateway.tenant, approval)
    assert ok.status_code == 200 and ok.json()["data"]["ok"], ok.text
    after = await _status(gateway, approval)
    assert (after["status"], after["decidedBy"]) == ("approved", "m.okafor@bank.example"), after


async def test_a_rejection_keeps_its_reason(gateway: Gateway) -> None:  # noqa: F811
    approval = await _ask(gateway)
    r = await apply_access(gateway.client, gateway.tenant, approval, "rejected", reason="Use the read-only module")
    assert r.status_code == 200 and r.json()["data"]["ok"], r.text
    after = await _status(gateway, approval)
    assert (after["status"], after["reason"]) == ("rejected", "Use the read-only module"), after


async def test_a_run_in_another_team_decides_nothing(gateway: Gateway) -> None:  # noqa: F811
    approval = await _ask(gateway)
    r = await apply_access(gateway.client, gateway.tenant, approval, team="team_fraud")
    assert r.status_code == 200 and not r.json()["data"]["ok"], r.text
    assert (await _status(gateway, approval))["status"] == "requested"


async def test_a_decision_applies_once_and_never_revives_a_revoked_request(gateway: Gateway) -> None:  # noqa: F811
    # A run retried after a timeout applies the same decision again under a new attempt; it changes nothing. A request
    # revoked on the module meanwhile stays revoked.
    approval = await _ask(gateway)
    for _ in range(2):
        r = await apply_access(gateway.client, gateway.tenant, approval)
        assert r.status_code == 200 and r.json()["data"]["output"]["status"] == "approved", r.text
    revoked = await _ask_other(gateway)
    body = {"ids": [revoked["id"]], "reason": "not needed"}
    assert (await gateway.client.post(f"{MODULES}/mod_core_banking/approvals/revoke", json=body)).is_success
    late = await apply_access(gateway.client, gateway.tenant, revoked)
    assert late.status_code == 200 and late.json()["data"]["output"]["code"] == "already_decided", late.text
    assert (await _status(gateway, revoked))["status"] == "revoked"


async def test_the_requester_does_not_approve_their_own_request(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    # Whoever asked for the access is not its approver, whichever run applies the decision.
    approval = await _ask(gateway)
    m = await ModuleStore(engine).get(gateway.tenant, "mod_core_banking")
    assert m is not None
    asker = next(a for a in m["approvals"] if a["id"] == approval["id"])["requested_by_email"]
    assert asker, "the request keeps its asker's email"
    r = await apply_access(gateway.client, gateway.tenant, approval, approvers=[asker.upper()])
    assert r.status_code == 200 and r.json()["data"]["output"]["code"] == "own_request", r.text
    assert (await _status(gateway, approval))["status"] == "requested"


class Platform:
    """platform-service's access check as tools-service asks it: whether `email` may decide their own request in the
    token's team, answered from who holds Approvals decide there now."""

    def __init__(self, holders: set[str]) -> None:
        self.holders = holders
        self.asked: list[tuple[str, str | None, str]] = []

    async def post(self, path: str, json: Any = None, *, tenant: str, team: str | None = None) -> Any:
        assert path == "/v1/access/check", path
        if (json["area"], json["action"]) != ("reviews", "decide"):
            # The send's own check of Tools · run: everyone here holds it.
            return {"allowed": True, "refusedBy": None}
        self.asked.append((tenant, team, json["email"]))
        if json["email"] in self.holders:
            return {"allowed": True, "refusedBy": None}
        reason = f"{json['email']} asked for this, so someone else has to decide it."
        return {"allowed": False, "refusedBy": {"code": "own_request", "reason": reason}}


async def _asked(gw: Gateway, engine: AsyncEngine) -> tuple[dict[str, Any], str, str]:
    approval = await _ask(gw)
    m = await ModuleStore(engine).get(gw.tenant, "mod_core_banking")
    assert m is not None
    asked = next(a for a in m["approvals"] if a["id"] == approval["id"])
    assert asked["requested_by_email"] and asked.get("decider_team"), asked
    return approval, str(asked["requested_by_email"]), str(asked["decider_team"])


def _service(engine: AsyncEngine, seed: dict[str, Any], platform: Platform) -> ModuleService:
    directory = Directory.from_seed(seed, datetime.now(UTC))
    return ModuleService(ModuleStore(engine), directory, CallLog(engine), own_requests=OwnRequests(cast(Any, platform)))


async def test_a_lone_admin_decides_her_own_access_request_through_the_system_workflow(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
    seed: dict[str, Any],
) -> None:
    """The decision arrives through the system workflow with no roles of the asker's to read; whether she holds
    Approvals decide in the deciding team is asked of platform-service now, so an Admin is approved."""
    approval, asker, team = await _asked(gateway, engine)
    platform = Platform({asker})
    kw: dict[str, Any] = {"approval_id": approval["id"], "decision": "approved", "reason": None, "by": asker}
    applied = await _service(engine, seed, platform).apply_access_decision(gateway.tenant, "mod_core_banking", **kw)
    assert applied["status"] == "approved", applied
    assert platform.asked == [(gateway.tenant, team, asker)], platform.asked


async def test_an_asker_without_the_cell_is_refused_whatever_her_acting_for_token_claims(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
    seed: dict[str, Any],
) -> None:
    """A Builder whose acting-for token claims Admin of the team is refused own_request: the live answer decides, never
    the token; a failed check refuses too."""
    approval, asker, team = await _asked(gateway, engine)
    claims_admin = principal_of(
        ActingForPerson(sub="usr_asker", email=asker, name=asker, team_id=team, access={"access": {team: ["admin"]}}),
        gateway.tenant,
    )
    kw: dict[str, Any] = {"approval_id": approval["id"], "decision": "approved", "reason": None, "by": asker}
    with pytest.raises(Forbidden) as refused:
        await _service(engine, seed, Platform(set())).apply_access_decision(
            gateway.tenant, "mod_core_banking", acting_for=claims_admin, **kw
        )
    assert refused.value.code == "own_request"

    class Down(Platform):
        async def post(self, path: str, json: Any = None, *, tenant: str, team: str | None = None) -> Any:
            raise ServiceUnreachable("platform did not answer")

    with pytest.raises(Forbidden) as down:
        await _service(engine, seed, Down({asker})).apply_access_decision(gateway.tenant, "mod_core_banking", **kw)
    assert down.value.code == "own_request"
    applied = await _service(engine, seed, Platform({asker})).apply_access_decision(
        gateway.tenant, "mod_core_banking", **kw
    )
    assert applied["status"] == "approved", applied
