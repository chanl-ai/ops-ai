"""The agent spec routes (docs/design/agents-v2/agent-spec-file.md), by failure mode: an applied file reads back
different from what was applied; a bad spec is saved, or refused without the field's path; a diff does not name the
section that changed; a draft whose spec stopped validating after its save is published; another tenant's agent is
read or written through the spec routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from httpx import AsyncClient

from ops_agents.api.deps import Runtime
from ops_agents.api.model_aliases import StaticModelAliases
from tests.api.test_registry_tenant_pins import person, published_agent, started, tenants

DESIGN = Path(__file__).parents[4] / "docs" / "design" / "agents-v2"
# The examples' tools and knowledge bases, as the fixture catalogue names its own.
RECORDS = {
    "core_banking.get_loan": "lookup_account",
    "core_banking.list_payments": "lookup_customer",
    "core_banking.post_payoff_quote": "place_wire_hold",
    "itsm.search_tickets": "search_customers",
    "itsm.create_ticket": "request_document",
    "directory.get_user": "get_customer",
    "kb_lending_policy": "kb_lending",
    "kb_it_runbooks": "kb_support",
}


def _mapped(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _mapped(v, ids) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [_mapped(v, ids) for v in cast(list[Any], value)]
    return ids.get(value, value) if isinstance(value, str) else value


def _ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def _records(client: AsyncClient, rt: Runtime, tenant: str) -> dict[str, str]:
    """The records the examples name, made in `tenant`: helper agents, a skill and two guardrails, each published."""
    rt.model_aliases = StaticModelAliases({"chat-default", "chat-fallback"})
    who = person(tenant)
    ids = dict(RECORDS)
    for helper in ("ag_credit_policy", "ag_payoff_calculator", "ag_access_requests", "ag_device_support"):
        ids[helper] = await published_agent(client, rt, tenant, helper.removeprefix("ag_").replace("_", " ").title())
    skill = {
        "name": f"Payoff quote {tenant}",
        "useWhen": "A loan officer asks for the amount that pays a loan off on a given day.",
        "instructions": "Look the loan up, then state the payoff amount and the date it holds to.",
        "toolIds": ["lookup_account"],
        "knowledgeBases": ["kb_lending"],
        "guardrails": ["Never quote a figure the core banking system did not return"],
    }
    sid = _ok(await client.post("/v1/skills", json=skill, headers=who), 201)["id"]
    _ok(await client.post(f"/v1/skills/{sid}/publish-requests", json={"note": ""}, headers=who), 201)
    ids["sk_payoff_quote"] = sid
    for gid, topic in (("gr_no_investment_advice", "investment advice"), ("gr_no_password_sharing", "passwords")):
        rule = {"name": f"No {topic} {tenant}", "topics": [topic], "message": f"I can't help with {topic}."}
        made = _ok(await client.post("/v1/guardrails", json=rule, headers=who), 201)["id"]
        _ok(await client.post(f"/v1/guardrails/{made}/publish-requests", json={"version": 1}, headers=who), 201)
        ids[gid] = made
    return ids


def _example(name: str, ids: dict[str, str]) -> dict[str, Any]:
    raw = yaml.safe_load((DESIGN / name).read_text())
    spec = cast(dict[str, Any], _mapped(raw, ids))
    # The records made here are at version 1.
    for key in ("skills", "guardrails"):
        refs = cast(list[Any], spec.get(key) or [])
        for item in refs:
            if isinstance(item, dict) and "version" in item:
                item["version"] = 1
    # The command line uploads a local file and sends its id; the server never stores `from`.
    sandbox = cast(dict[str, Any], spec.get("sandbox") or {})
    for f in cast(list[dict[str, Any]], sandbox.get("files") or []):
        f["fileId"] = "fil_parse_syslog"
        del f["from"]
    return spec


async def _new_agent(client: AsyncClient, who: dict[str, str], name: str) -> dict[str, Any]:
    made = _ok(await client.post("/v1/agents", json={"name": name, "role": "Drafted"}, headers=who), 201)
    return cast(dict[str, Any], _ok(await client.get(f"/v1/agents/{made['id']}/spec", headers=who)))


async def _apply(client: AsyncClient, who: dict[str, str], view: dict[str, Any], spec: dict[str, Any]) -> Any:
    body = {"spec": spec, "baseVersion": view["version"], "baseDigest": view["digest"]}
    return await client.put(f"/v1/agents/{view['agentId']}/spec", json=body, headers=who)


async def test_both_examples_validate_and_read_back_as_applied(database_url: str) -> None:
    a, _ = tenants()
    async with started(database_url) as (client, rt):
        ids = await _records(client, rt, a)
        who = person(a)
        for name in ("agent-spec-loan-ops.yaml", "agent-spec-it-helpdesk.yaml"):
            spec = _example(name, ids)
            checked = _ok(await client.post("/v1/agents/spec/validate", json={"spec": spec}, headers=who))
            assert checked["ok"], (name, checked["problems"])
            view = await _new_agent(client, who, spec["name"])
            _ok(await _apply(client, who, view, spec))
            back = _ok(await client.get(f"/v1/agents/{view['agentId']}/spec", headers=who))
            assert back["spec"] == {**spec, "id": view["agentId"]}, name
            # The console's editor reads the same version.
            agent = _ok(await client.get(f"/v1/agents/{view['agentId']}", headers=who))
            assert agent["digest"] == back["digest"]


async def test_a_bad_spec_is_refused_with_the_field_path_and_nothing_is_saved(database_url: str) -> None:
    a, _ = tenants()
    async with started(database_url) as (client, rt):
        rt.model_aliases = StaticModelAliases({"chat-default"})
        who = person(a)
        view = await _new_agent(client, who, "Claims intake")
        spec = {
            "apiVersion": "ops.ai/v2",
            "name": "Claims intake",
            "role": "Opens insurance claims from a policyholder's first report.",
            "toolIds": ["lookup_customer", "claims.open_claim"],
            "loop": {"kind": "supervisor", "maxStepz": 4},
        }
        refused = await _apply(client, who, view, spec)
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "spec_invalid"
        assert {(p["path"], p["code"]) for p in error["details"]["problems"]} == {("/loop/maxStepz", "schema")}
        del cast(dict[str, Any], spec["loop"])["maxStepz"]
        refused = await _apply(client, who, view, spec)
        assert refused.status_code == 422, refused.text
        assert [(p["path"], p["code"]) for p in refused.json()["error"]["details"]["problems"]] == [
            ("/toolIds/1", "unknown_tool")
        ]
        after = _ok(await client.get(f"/v1/agents/{view['agentId']}/spec", headers=who))
        assert (after["version"], after["digest"]) == (view["version"], view["digest"])


async def test_a_diff_names_the_section_that_changed(database_url: str) -> None:
    a, _ = tenants()
    async with started(database_url) as (client, rt):
        ids = await _records(client, rt, a)
        who = person(a)
        spec = _example("agent-spec-loan-ops.yaml", ids)
        view = await _new_agent(client, who, spec["name"])
        _ok(await _apply(client, who, view, spec))
        changed = {**spec, "limits": {"budget": {"defaultUsd": 0.5, "ceilingUsd": 3.0}}}
        found = _ok(await client.post(f"/v1/agents/{view['agentId']}/spec/diff", json={"spec": changed}, headers=who))
        assert [(c["op"], c["path"], c["before"], c["after"]) for c in found["changes"]] == [
            ("replace", "/limits/budget/ceilingUsd", 2.0, 3.0)
        ]


async def test_a_draft_whose_helper_is_gone_is_not_published(database_url: str) -> None:
    a, _ = tenants()
    async with started(database_url) as (client, rt):
        ids = await _records(client, rt, a)
        who = person(a)
        spec = _example("agent-spec-loan-ops.yaml", ids)
        view = await _new_agent(client, who, spec["name"])
        saved = _ok(await _apply(client, who, view, spec))
        gone = await client.delete(f"/v1/agents/{ids['ag_payoff_calculator']}", headers=who)
        assert gone.status_code == 204, gone.text
        asked = await client.post(
            f"/v1/agents/{view['agentId']}/publish-requests", json={"version": saved["version"]}, headers=who
        )
        assert asked.status_code == 422, asked.text
        assert asked.json()["error"]["code"] == "cannot_publish"
        assert "/agents/1/id, helper_unknown" in asked.json()["error"]["message"]


async def test_another_tenants_agent_is_not_found_on_every_spec_route(database_url: str) -> None:
    a, b = tenants()
    async with started(database_url) as (client, rt):
        rt.model_aliases = StaticModelAliases({"chat-default"})
        view = await _new_agent(client, person(a), "Shipment tracker")
        theirs = person(b)
        spec = {"apiVersion": "ops.ai/v2", "name": "Shipment tracker", "role": "Tracks freight shipments."}
        path = f"/v1/agents/{view['agentId']}/spec"
        read = await client.get(path, headers=theirs)
        assert read.status_code == 404, read.text
        write = await _apply(client, theirs, view, spec)
        assert write.status_code == 404, write.text
        compared = await client.post(f"{path}/diff", json={"spec": spec}, headers=theirs)
        assert compared.status_code == 404, compared.text
        mine = _ok(await client.get(path, headers=person(a)))
        assert (mine["version"], mine["digest"]) == (view["version"], view["digest"])
