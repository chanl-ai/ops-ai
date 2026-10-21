"""The stack the AI step use cases (uc-258 to uc-262, c-298) share: platform-service for the team's aiSteps setting,
models-service on the fake OpenAI with the ai-steps-fake-openai rules (agents-service tests/fixtures), the agents
service reading platform policies, and a workflow worker. No real model is called."""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import httpx
from usecase_harness import AGENTS_DIR, agents, bearer, data, engine_worker, fake_openai, models, platform, signed_in

RULES = AGENTS_DIR / "tests" / "fixtures" / "ai-steps-fake-openai"
OPS = {"X-Team-Id": "team_ops"}


@contextmanager
def ai_stack(name: str) -> Generator[tuple[httpx.Client, httpx.Client]]:
    """(agents API, platform API)."""
    with (
        platform() as (people, _inner),
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
    ):
        platform_url = str(people.base_url).rstrip("/")
        with (
            agents(models_url=models_url, models_key="mk_dev_agents", env={"OPS_PLATFORM_URL": platform_url}) as api,
            engine_worker(
                name,
                {"OPS_MODELS_URL": models_url, "OPS_MODELS_KEY": "mk_dev_agents", "OPS_PLATFORM_URL": platform_url},
            ),
        ):
            yield api, people


def turn_on(people: httpx.Client, key: str = "aiSteps", team: str = "team_ops") -> httpx.Response:
    """Priya Shah, admin of team_ops, turns an AI feature on for the team (Govern > Policies): aiSteps or taskAssist."""
    priya = bearer(signed_in(people, "p.shah@harborpine.example"), team)
    return people.put(f"/v1/policies/{key}", json={"value": True}, headers=priya)


def definition(wid: str, steps: list[dict[str, Any]], wires: list[tuple[str, str, str]]) -> dict[str, Any]:
    """A request-triggered workflow of `steps`, wired `(from, port, to)`; every end is an outcome named after it."""
    ends = sorted({to for _f, _p, to in wires if to.startswith("end_")})
    nodes = [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        *steps,
        *[{"id": e, "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": e[4:]}} for e in ends],
    ]
    connections = [{"from": {"node": f, "port": p}, "to": {"node": t, "port": "in"}} for f, p, t in wires]
    return {"schemaVersion": 2, "id": wid, "name": wid, "nodes": nodes, "connections": connections}


def save(api: httpx.Client, d: dict[str, Any]) -> httpx.Response:
    return api.post("/v1/workflows/definitions", json={"definition": d}, headers=OPS)


def publish(api: httpx.Client, d: dict[str, Any]) -> None:
    saved = save(api, d)
    if saved.status_code not in (200, 201):
        raise RuntimeError(f"setup: save {d['id']} answered {saved.status_code}: {saved.text[:400]}")
    live = data(api.post(f"/v1/workflows/definitions/{d['id']}/publish-requests", json={}, headers=OPS))
    if live["status"] != "approved":
        raise RuntimeError(f"setup: publish {d['id']}: {live}")


def run(api: httpx.Client, wid: str, text: str) -> dict[str, Any]:
    """The finished run's detail: status, outcome and each step's port and output, by node id under `steps`."""
    started = data(api.post("/v1/runs", json={"workflowId": wid, "mode": "live", "input": {"body": text}}, headers=OPS))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        detail = data(api.get(f"/v1/runs/{started['runId']}", headers=OPS))
        if detail["status"] in ("succeeded", "failed", "cancelled"):
            return detail | {"byNode": {s.get("nodeId"): s for s in detail["steps"]}}
        time.sleep(0.5)
    return {"status": "timed out", "byNode": {}}
