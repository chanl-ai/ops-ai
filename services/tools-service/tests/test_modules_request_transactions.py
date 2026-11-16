"""How many transactions the tool-module routes hold, by failure mode: a route opening one transaction per store call,
so a module page reads its rows, versions and connection at different moments and a write lands without the row read
to check it; and a connection held while platform-service answers which writes wait. The routes that ask another party
on the way (discover, import, create, test, run, publish, reviews, approvals) hold none (`modules/routes.py`). Seeded
as the statement budget seeds a team."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from ops_service_kit.logging import captured_logging
from ops_service_kit.testing import SeedTeam
from ops_tools.modules.policy import WriteApprovals

from . import test_statement_budget as budget

app = budget.app
client = budget.client
seed_team = budget.seed_team


async def test_a_modules_reads_and_local_writes_each_hold_one_transaction(
    client: httpx.AsyncClient, seed_team: SeedTeam
) -> None:
    seeded = await seed_team(2)
    c, admin = client, dict(seeded.headers)
    made = await c.post("/v1/tool-modules/blank", json={"displayName": "Desk tx", "name": "desk-tx"}, headers=admin)
    assert made.status_code == 201, made.text
    mod = made.json()["data"]["id"]
    module, call = seeded.ids["module_id"], seeded.ids["call_id"]
    steps: list[tuple[str, str, str, Any]] = [
        ("list", "GET", "/v1/tool-modules", None),
        ("grants", "GET", "/v1/tool-modules/grants", None),
        ("one", "GET", f"/v1/tool-modules/{module}", None),
        ("activity", "GET", f"/v1/tool-modules/{module}/activity", None),
        ("calls", "GET", "/v1/executions", None),
        ("call", "GET", f"/v1/executions/{call}", None),
        ("details", "PATCH", f"/v1/tool-modules/{mod}", {"description": "Desk tools"}),
        ("connection", "PUT", f"/v1/tool-modules/{mod}/connection", {"connectionId": None}),
        ("revoke", "POST", f"/v1/tool-modules/{mod}/approvals/revoke", {"ids": ["apr_none"], "reason": "tx"}),
        ("bulk delete", "POST", "/v1/tool-modules/bulk-delete", {"ids": ["mod_none"]}),
        ("delete", "DELETE", f"/v1/tool-modules/{mod}", None),
    ]
    counts: dict[str, int] = {}
    for name, method, path, body in steps:
        r, counts[name] = await _counted(c, method, path, body, admin)
        assert r.status_code in (200, 201, 204), (name, r.text)
    assert counts == {name: 1 for name, *_ in steps}, counts


@pytest.fixture
def engines(monkeypatch: pytest.MonkeyPatch) -> list[AsyncEngine]:
    """Every engine the app and the seed open, the app's first, so a test reads how many connections are out."""
    made: list[AsyncEngine] = []
    real = budget.open_database

    def recording(url: str) -> AsyncEngine:
        made.append(real(url))
        return made[-1]

    monkeypatch.setattr(budget, "open_database", recording)
    return made


async def test_no_connection_is_held_while_platform_says_which_writes_wait(
    engines: list[AsyncEngine], client: httpx.AsyncClient, seed_team: SeedTeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await seed_team(1)
    held: list[int] = []
    asked = WriteApprovals.levels

    async def watched(self: WriteApprovals, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        held.append(sum(e.pool.checkedout() for e in engines if isinstance(e.pool, QueuePool)))
        return await asked(self, tenant_id, team_id)

    monkeypatch.setattr(WriteApprovals, "levels", watched)
    r = await client.get(f"/v1/tool-modules/{seeded.ids['module_id']}", headers=dict(seeded.headers))
    assert (r.status_code, held) == (200, [0]), r.text


async def _counted(
    c: httpx.AsyncClient, method: str, path: str, body: object, headers: dict[str, str]
) -> tuple[httpx.Response, int]:
    """The answer and how many transactions the request held, from its request line."""
    with captured_logging("tools-modules-tx") as stream:
        r = await c.request(method, path, json=body, headers=headers)
    line = next(json.loads(x) for x in stream.getvalue().splitlines() if '"http.request"' in x)
    return r, int(line["db.tx_count"])
