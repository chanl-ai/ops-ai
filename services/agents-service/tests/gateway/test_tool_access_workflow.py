"""A tool access request runs as the tool_access_request event workflow (c-257), through the real event route, worker,
Human Tasks and gateway. By failure mode: the request opens no review; the sheet loses what the reviewer decides on;
the requester decides their own request; the decision never reaches the module, or reaches it under nobody or
without its reason; and a team's own workflow, built like the handler, grants access through the same tool."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from ops_engine.worker import Worker
from ops_identity import dev_service_signer, mint_service_token

from .conftest import Gateway
from .test_engine_reviewed_write import REVIEWER, STARTER, finish, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]

TEAM = {"X-Team-Id": "team_ops"}


def tools_service() -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="tools",
        audience="agents",
        tenant_id="local",
        scopes=["events:emit"],
        team_id="team_ops",  # the event's team, as tools-service's relay mints it
    )
    return {"Authorization": f"Bearer {token}"}


def payload(approval_id: str) -> dict[str, Any]:
    return {
        "moduleId": "mod_core_banking",
        "moduleName": "Core banking",
        "approvalId": approval_id,
        "workflowId": "wf_dispute",
        "workflowName": "Dispute email",
        "operations": ["get_customer_profile"],
        "environment": "production",
        "expiresAt": "2026-11-17T00:00:00+00:00",
        "justification": "Holds during a dispute",
        "deciderTeam": "team_ops",
        "requestedBy": "James Richardson",
    }


async def requested(client: httpx.AsyncClient, worker: Worker) -> tuple[str, str]:
    """tools-service reports a request by James; the run waits at its review. Returns (run id, run key)."""
    key = f"apr_{uuid4().hex[:10]}"
    body = {
        "name": "tool_access.requested",
        "key": key,
        "teamId": "team_ops",
        "actor": STARTER["X-Dev-User"],
        "payload": payload(key),
    }
    r = await client.post("/v1/events", json=body, headers=tools_service())
    assert r.status_code == 202 and r.json()["data"]["status"] == "started", r.text
    [run_id] = r.json()["data"]["runIds"]
    assert (await finish(worker, client, run_id))["status"] == "waiting"
    return run_id, f"tool_access.requested:{key}"


async def test_the_request_waits_in_human_tasks_and_an_approval_grants_it(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
    gateway: Gateway,
) -> None:
    client, worker = stack
    run_id, run_key = await requested(client, worker)
    sheet = await client.get(f"/reviews/by-run-key/{run_key}", headers=REVIEWER | TEAM)
    assert sheet.status_code == 200, sheet.text
    review = sheet.json()["data"]
    assert review["title"] == "Let Dispute email use Core banking?", review["title"]
    # The row reads from the task and the step's requestedBy, as every typed review's does (no per-workflow sheet).
    assert review["reasoning"] == ["Holds during a dispute"], review["reasoning"]
    # The tool_access_request task type draws the same question (c-288), with the actions it declares.
    task = review["task"]
    assert task["type"]["id"] == "tool_access_request", task["type"]
    assert task["regions"][0]["data"] == {"title": "Let Dispute email use Core banking?"}, task["regions"]
    assert [a["label"] for a in task["actions"]] == ["Grant", "Refuse"], task["actions"]
    # Round 4: the asker may be an agent, Refuse says what it does, and the grant's call is not listed as history.
    facts = next(r["data"]["facts"] for r in task["regions"] if r["region"] == "facts")
    assert facts[0]["label"] == "Used by", facts
    assert task["actions"][1]["consequence"] == "Nothing changes, and your reason is kept with the request."
    assert review["evidence"] == [], review["evidence"]
    own = await client.post(f"/reviews/{run_id}/decision", json={"decision": "approve"}, headers=STARTER | TEAM)
    assert own.status_code == 403, "the person who asked does not decide it"
    ok = await client.post(f"/reviews/{run_id}/decision", json={"decision": "approve"}, headers=REVIEWER | TEAM)
    assert ok.status_code == 200, ok.text
    done = await finish(worker, client, run_id)
    assert done["outcome"] == "granted", done
    [applied] = gateway.decisions.applied
    assert (applied["approval_id"], applied["decision"], applied["by"], applied["team_id"]) == (
        run_key.split(":", 1)[1],
        "approved",
        REVIEWER["X-Dev-User"],
        "team_ops",
    ), applied


async def test_a_rejection_reaches_the_module_with_its_reason(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
    gateway: Gateway,
) -> None:
    client, worker = stack
    run_id, _ = await requested(client, worker)
    body = {"decision": "reject", "inputs": {"reason": "Use the read-only module"}}
    r = await client.post(f"/reviews/{run_id}/decision", json=body, headers=REVIEWER | TEAM)
    assert r.status_code == 200, r.text
    assert (await finish(worker, client, run_id))["outcome"] == "refused"
    [applied] = gateway.decisions.applied
    assert (applied["decision"], applied["reason"]) == ("rejected", "Use the read-only module"), applied


async def test_a_team_workflow_built_like_the_handler_grants_nothing(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
    gateway: Gateway,
) -> None:
    from ops_agents.api.event_workflows import EVENT_WORKFLOWS  # noqa: PLC0415 - the definition copied

    tool_access_request = next(w for w in EVENT_WORKFLOWS if w["id"] == "tool_access_request")

    client, worker = stack
    nodes: list[dict[str, Any]] = list(tool_access_request["nodes"])
    copy: dict[str, Any] = {
        **tool_access_request,
        "id": f"wf_grants_{uuid4().hex[:6]}",
        "nodes": [{**n, "type": "ops.trigger.request", "parameters": {}} if n["id"] == "start" else n for n in nodes],
    }
    # Saved in a team, as every workflow is: its typed steps are checked against that team's task types.
    saved = await client.post("/v1/workflows/definitions", json={"definition": copy}, headers=TEAM)
    assert saved.status_code in (200, 201), saved.text
    asked = await client.post(f"/v1/workflows/definitions/{copy['id']}/publish-requests", json={}, headers=TEAM)
    assert asked.status_code == 201, asked.text
    start = {"workflowId": copy["id"], "input": payload("apr_forged")}
    run_id = str((await client.post("/v1/runs", json=start, headers=STARTER)).json()["data"]["runId"])
    assert (await finish(worker, client, run_id))["status"] == "waiting"
    r = await client.post(f"/reviews/{run_id}/decision", json={"decision": "approve"}, headers=REVIEWER)
    assert r.status_code == 200, r.text
    done = await finish(worker, client, run_id)
    assert done["outcome"] == "not_applied" and gateway.decisions.applied == [], done


async def test_the_asker_named_in_the_request_does_not_decide_it_while_the_policy_is_off(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
    gateway: Gateway,
) -> None:
    # The step names whoever asked (requestedBy) even when the event names no actor, so the run's creator is the event
    # (tick 25); they are refused under the tenant's requesterMayDecide, off in this stack, as a run's starter is (tick
    # 29), not whatever the policy.
    client, worker = stack
    key = f"apr_{uuid4().hex[:10]}"
    body = {
        "name": "tool_access.requested",
        "key": key,
        "teamId": "team_ops",
        "payload": payload(key) | {"requestedByEmail": STARTER["X-Dev-User"]},
    }
    r = await client.post("/v1/events", json=body, headers=tools_service())
    [run_id] = r.json()["data"]["runIds"]
    assert (await finish(worker, client, run_id))["status"] == "waiting"
    own = await client.post(f"/reviews/{run_id}/decision", json={"decision": "approve"}, headers=STARTER | TEAM)
    assert (own.status_code, own.json()["error"]["code"]) == (403, "own_request"), own.text
    assert gateway.decisions.applied == []
