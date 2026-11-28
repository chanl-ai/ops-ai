"""Every `/v1/cases` route's reply, status and error object, value by value, by failure mode: a case row or page key
the console reads changing; a refusal (a stray body field, a cleared subject, a note with no text, a self link,
another team's case) changing its status or code. Seconds left on a clock are pinned as present or not, since they
count down. Regenerate with `AGENTS_REPIN=1` only for an intended change."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api import case_page
from ops_agents.api.actors import named_actors
from ops_agents.api.routers import case_records
from tests.api import role_app as role_app_module
from tests.api.test_reply_pins import FIXTURES, answer, compare
from tests.conftest import scripted_model
from tests.engine.test_lifecycle_rights import BUILDER, VIEWER, person

from .role_app import role_app

_ENGINES: list[AsyncEngine] = []
_CASE_ID = re.compile(r"\bcase_[0-9a-f]{12}\b")
OTHER_TEAM = person("omar", "team_fraud", "builder")
DISPUTE: dict[str, Any] = {"subject": "Card dispute", "priority": "high", "customerId": "C-1001", "customerName": "Ann"}


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    made = role_app_module.create_async_engine

    def kept(*args: Any, **kwargs: Any) -> AsyncEngine:
        _ENGINES.append(engine := made(*args, **kwargs))
        return engine

    monkeypatch.setattr(role_app_module, "create_async_engine", kept)
    async with role_app(scripted_model()) as c:
        yield c


def _steady(value: Any) -> Any:
    """`value` with each seconds-left count replaced by whether it is set, and a case id in a message by its kind."""
    if isinstance(value, dict):
        held = cast(dict[str, Any], value)
        return {k: (v is not None) if k.endswith(("LeftS", "leftS")) else _steady(v) for k, v in held.items()}
    if isinstance(value, list):
        return [_steady(v) for v in cast(list[Any], value)]
    return _CASE_ID.sub("<case>", value) if isinstance(value, str) else value


async def test_every_case_route_keeps_its_reply_status_and_error_object(client: AsyncClient) -> None:
    c = client
    seen: dict[str, Any] = {}
    opened = await c.post("/v1/cases", json={**DISPUTE, "producerKey": "run_pin1"}, headers=VIEWER)
    case = opened.json()["data"]["id"]
    other = (await c.post("/v1/cases", json={**DISPUTE, "subject": "Late fee"}, headers=VIEWER)).json()["data"]["id"]
    theirs = (await c.post("/v1/cases", json=DISPUTE, headers=OTHER_TEAM)).json()["data"]["id"]
    seen["open"] = answer(opened)
    retried = await c.post("/v1/cases", json={**DISPUTE, "producerKey": "run_pin1"}, headers=VIEWER)
    assert retried.json()["data"]["id"] == case, "a producer's retry finds the case it opened"
    seen["openRetry"] = answer(retried)
    seen["openStray"] = answer(await c.post("/v1/cases", json={**DISPUTE, "colour": 1}, headers=VIEWER))
    seen["openBadPriority"] = answer(await c.post("/v1/cases", json={**DISPUTE, "priority": "soon"}, headers=VIEWER))
    seen["list"] = answer(await c.get("/v1/cases", params={"pageSize": 1, "page": 2}, headers=VIEWER))
    seen["listSearch"] = answer(await c.get("/v1/cases", params={"search": "late"}, headers=VIEWER))
    seen["listOtherTeam"] = answer(await c.get("/v1/cases", headers=OTHER_TEAM))
    seen["listBadSize"] = answer(await c.get("/v1/cases", params={"pageSize": 101}, headers=VIEWER))
    url = f"/v1/cases/{case}"
    seen["patch"] = answer(await c.patch(url, json={"priority": "low", "assignee": "james@x.example"}, headers=VIEWER))
    seen["patchClears"] = answer(await c.patch(url, json={"subject": None}, headers=VIEWER))
    seen["patchStray"] = answer(await c.patch(url, json={"colour": 1}, headers=VIEWER))
    seen["patchOtherTeam"] = answer(await c.patch(url, json={"priority": "low"}, headers=OTHER_TEAM))
    seen["note"] = answer(await c.post(f"{url}/events", json={"text": "Asked for the receipt"}, headers=VIEWER))
    seen["noteEmpty"] = answer(await c.post(f"{url}/events", json={"kind": "note"}, headers=VIEWER))
    seen["runNoRef"] = answer(await c.post(f"{url}/events", json={"kind": "run"}, headers=VIEWER))
    seen["runMissing"] = answer(await c.post(f"{url}/events", json={"kind": "run", "ref": "run_none1"}, headers=VIEWER))
    seen["link"] = answer(await c.post(f"{url}/links", json={"caseId": other}, headers=BUILDER))
    seen["linkSelf"] = answer(await c.post(f"{url}/links", json={"caseId": case}, headers=BUILDER))
    seen["linkOtherTeam"] = answer(await c.post(f"{url}/links", json={"caseId": theirs}, headers=BUILDER))
    seen["read"] = answer(await c.get(url, headers=VIEWER))
    seen["readOtherTeam"] = answer(await c.get(url, headers=OTHER_TEAM))
    seen["readMissing"] = answer(await c.get("/v1/cases/case_none1", headers=VIEWER))
    # The run list and human tasks beside them (cases.py, tasks.py), pinned here as they had no table of their own.
    seen["runs.list"] = answer(await c.get("/runs", params={"pageSize": 3}, headers=VIEWER))
    seen["runs.missing"] = answer(await c.get("/runs/th_none1", headers=VIEWER))
    task = {"type": "no_such_type", "params": {"payee": "Acme"}}
    seen["tasks.unknownType"] = answer(await c.post("/v1/tasks", json=task, headers=BUILDER))
    seen["tasks.stray"] = answer(await c.post("/v1/tasks", json={**task, "colour": 1}, headers=BUILDER))
    seen["tasks.missing"] = answer(await c.get("/v1/tasks/tk_none1", headers=VIEWER))
    compare(_steady(seen), FIXTURES / "reply-pins-case-records.json")


async def test_each_case_route_holds_one_transaction_and_none_while_people_are_named(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A change, note or link half written, or a connection held while platform-service names the owners."""
    c = client
    begun: list[int] = []
    ended: list[int] = []
    held_while_naming: list[int] = []

    def began(_conn: object) -> None:
        begun.append(1)

    def finished(_conn: object) -> None:
        ended.append(1)

    sync = _ENGINES[-1].sync_engine
    event.listen(sync, "begin", began)
    event.listen(sync, "commit", finished)
    event.listen(sync, "rollback", finished)

    async def watched_named(rt: Any, reads: Any) -> dict[str, dict[str, Any]]:
        held_while_naming.append(len(begun) - len(ended))
        return await named_actors(rt, reads)

    monkeypatch.setattr(case_records, "named_actors", watched_named)
    monkeypatch.setattr(case_page, "named_actors", watched_named)
    other = (await c.post("/v1/cases", json=DISPUTE, headers=VIEWER)).json()["data"]["id"]
    url = f"/v1/cases/{(await c.post('/v1/cases', json=DISPUTE, headers=VIEWER)).json()['data']['id']}"
    steps: list[tuple[str, str, str, object]] = [
        ("open", "POST", "/v1/cases", {**DISPUTE, "subject": "Late fee"}),
        ("change", "PATCH", url, {"priority": "low", "assignee": "vera@harborpine.example"}),
        ("note", "POST", f"{url}/events", {"text": "Asked for the receipt"}),
        ("link", "POST", f"{url}/links", {"caseId": other}),
    ]
    counts: dict[str, int] = {}
    for name, method, path, body in steps:
        begun.clear()
        ended.clear()
        r = await c.request(method, path, json=body, headers=VIEWER)
        assert r.status_code in (200, 201), (name, r.text)
        counts[name] = len(begun)
    for name, path in (("list", "/v1/cases"), ("read", url)):
        r = await c.get(path, headers=VIEWER)
        assert r.status_code == 200, (name, r.text)
    assert (counts, held_while_naming) == (dict.fromkeys(counts, 1), [0, 0]), (counts, held_while_naming)
