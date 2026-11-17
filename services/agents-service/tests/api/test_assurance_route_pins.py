"""Every Evals route's reply, status and error object, value by value, by failure mode: a suite, run or publish check
row changing a key the Evals page reads; a saved case's reply changing shape; a refusal (a viewer saving, an unknown
check type, a case for an agent or skill that is not there, a stray body field) changing its status or code; and an
eval-case route opening a transaction per store call, so a replace and the cases read back come from different
moments. Regenerate with `AGENTS_REPIN=1` only for an intended change."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from tests.api import test_write_approval_policy as platform_stub
from tests.api.test_assurance import FAILING, OPS, PASSING, who
from tests.api.test_reply_pins import FIXTURES, answer, compare
from tests.api.test_skills import HARDSHIP
from tests.api.test_write_approval_policy import _client  # pyright: ignore[reportPrivateUsage]
from tests.conftest import SEED

_ENGINES: list[AsyncEngine] = []
# A link or a message names a generated id inside a longer string, which `answer` leaves as it is.
_INSIDE = re.compile(r"\b([a-z]{2})_[0-9a-f]{12}\b")


def _seen(r: Response) -> dict[str, Any]:
    return json.loads(_INSIDE.sub(r"<\1>", json.dumps(answer(r))))


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    made = platform_stub.create_async_engine

    def kept(*args: Any, **kwargs: Any) -> AsyncEngine:
        _ENGINES.append(engine := made(*args, **kwargs))
        return engine

    monkeypatch.setattr(platform_stub, "create_async_engine", kept)
    async for c in _client(Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED), platform=True):
        yield c


async def _assets(c: AsyncClient) -> tuple[str, str]:
    agent = await c.post("/v1/agents", json={"name": "Payee Checker", "role": "Checks payees"}, headers=OPS)
    skill = await c.post("/v1/skills", json=HARDSHIP, headers=OPS)
    assert (agent.status_code, skill.status_code) == (201, 201), (agent.text, skill.text)
    return agent.json()["data"]["id"], skill.json()["data"]["id"]


async def test_every_evals_route_keeps_its_reply_status_and_error_object(client: AsyncClient) -> None:
    c, viewer = client, who("usr_v", "viewer")
    aid, sid = await _assets(c)
    seen: dict[str, Any] = {}
    agent_cases, skill_cases = f"/v1/agents/{aid}/eval-cases", f"/v1/skills/{sid}/eval-cases"
    seen["agent.save"] = _seen(await c.put(agent_cases, json={"cases": [PASSING, FAILING]}, headers=OPS))
    seen["agent.read"] = _seen(await c.get(agent_cases, headers=viewer))
    seen["agent.viewerSaves"] = _seen(await c.put(agent_cases, json={"cases": [PASSING]}, headers=viewer))
    bad = {"name": "x", "input": "y", "checks": [{"type": "rubric", "text": "kind"}]}
    seen["agent.unknownCheck"] = _seen(await c.put(agent_cases, json={"cases": [bad]}, headers=OPS))
    seen["agent.stray"] = _seen(await c.put(agent_cases, json={"cases": [], "colour": "red"}, headers=OPS))
    seen["agent.missing"] = _seen(await c.get("/v1/agents/ag_missing1/eval-cases", headers=OPS))
    seen["skill.save"] = _seen(await c.put(skill_cases, json={"cases": [PASSING]}, headers=OPS))
    seen["skill.read"] = _seen(await c.get(skill_cases, headers=OPS))
    seen["skill.missing"] = _seen(await c.put("/v1/skills/sk_missing1/eval-cases", json={"cases": []}, headers=OPS))
    assert (await c.post(f"/v1/agents/{aid}/eval-runs", headers=OPS)).status_code < 300
    for tab in ("suites", "runs", "gates"):
        seen[tab] = _seen(await c.get(f"/v1/assurance/{tab}", params={"pageSize": 5}, headers=OPS))
    seen["suites.filtered"] = _seen(
        await c.get("/v1/assurance/suites", params={"kind": "skill", "search": "hard"}, headers=OPS)
    )
    seen["runs.pastEnd"] = _seen(await c.get("/v1/assurance/runs", params={"pageSize": 5, "page": 9}, headers=OPS))
    seen["suites.chatUser"] = _seen(await c.get("/v1/assurance/suites", headers=who("usr_c", "chat_user")))
    compare(seen, FIXTURES / "reply-pins-assurance.json")


async def test_each_eval_case_route_holds_one_transaction(client: AsyncClient) -> None:
    c = client
    aid, sid = await _assets(c)
    steps: list[tuple[str, str, str, object]] = [
        ("agent.save", "PUT", f"/v1/agents/{aid}/eval-cases", {"cases": [PASSING]}),
        ("agent.read", "GET", f"/v1/agents/{aid}/eval-cases", None),
        ("skill.save", "PUT", f"/v1/skills/{sid}/eval-cases", {"cases": [PASSING]}),
        ("skill.read", "GET", f"/v1/skills/{sid}/eval-cases", None),
    ]
    begun: list[int] = []

    def began(_conn: object) -> None:
        begun.append(1)

    event.listen(_ENGINES[-1].sync_engine, "begin", began)
    counts: dict[str, int] = {}
    for name, method, path, body in steps:
        begun.clear()
        r = await c.request(method, path, json=body, headers=OPS)
        assert r.status_code == 200, (name, r.text)
        counts[name] = len(begun)
    assert counts == {name: 1 for name, *_ in steps}, counts
