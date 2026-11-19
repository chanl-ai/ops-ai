"""`GET /v1/executions` on the shared list contract, as a person: each filter (result, assistant, search over the tool's
name) narrows in SQL and the total, the two facets count the rows the other filter leaves, another team's and another
tenant's calls never appear, and a page past the end answers the last page with the true total."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.calls import gateway_calls

from .test_egress_and_secrets_need_security_admin import client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person


async def _log(
    engine: AsyncEngine, tenant: str, team: str, n: str, *, tool: str, outcome: str, assistant: str | None
) -> None:
    row: dict[str, Any] = {
        "id": f"call_{n}",
        "tool": tool,
        "access": "read",
        "input_hash": n,
        "idempotency_key": n,
        "sub": "user:sam",
        "decision": "deny" if outcome == "refused" else "allow",
        "reasons": [],
        "approvers": [],
        "outcome": outcome,
        "effect": False,
        "effect_scope": f"row:call_{n}",
        "created_at": "2026-11-01T10:00:00+00:00",  # equal for every row: only the id orders them
        "tenant_id": tenant,
        "team_id": team,
        "client_name": assistant,
    }
    async with engine.begin() as c:
        await c.execute(sa.insert(gateway_calls).values(**row))


async def test_each_filter_total_and_facet_hold_the_acting_teams_calls_only(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    mine = "team_platform"
    for n, tool, outcome, who in (
        ("a1", "get_account", "ok", "Claude"),
        ("a2", "get_account", "replayed", "Claude"),
        ("a3", "place_hold", "refused", "Claude"),
        ("a4", "place_hold", "error", None),
        ("a5", "get_case", "ok", "Cursor"),
    ):
        await _log(engine, tenant, mine, n, tool=tool, outcome=outcome, assistant=who)
    await _log(engine, tenant, "team_other", "b1", tool="get_account", outcome="ok", assistant="Claude")
    await _log(engine, f"{tenant}_other", mine, "c1", tool="get_account", outcome="ok", assistant="Claude")
    admin = person(tenant, "Sam Adeyemi", {mine: "admin"})

    async def ask(**params: Any) -> dict[str, Any]:
        r = await client.get("/v1/executions", params=params, headers=admin)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    page = await ask()
    assert [x["id"] for x in page["data"]] == ["call_a5", "call_a4", "call_a3", "call_a2", "call_a1"]
    assert page["pagination"]["total"] == 5
    assert page["facets"] == {
        "result": {"Ran": 3, "Refused": 1, "Failed": 1},
        "assistant": {"Claude": 3, "Cursor": 1, "Unnamed assistant": 1},
    }
    ran = await ask(result="Ran")
    assert (ran["pagination"]["total"], sorted(x["id"] for x in ran["data"])) == (3, ["call_a1", "call_a2", "call_a5"])
    # A facet leaves its own filter out, so the other choices in its menu keep their counts.
    assert ran["facets"]["result"] == {"Ran": 3, "Refused": 1, "Failed": 1}
    assert ran["facets"]["assistant"] == {"Claude": 2, "Cursor": 1}
    unnamed = await ask(assistant="Unnamed assistant")
    assert [x["id"] for x in unnamed["data"]] == ["call_a4"]
    both = await ask(result=["Ran", "Failed"], assistant=["Claude", "Unnamed assistant"])
    assert sorted(x["id"] for x in both["data"]) == ["call_a1", "call_a2", "call_a4"]
    found = await ask(search="hold")
    assert (found["pagination"]["total"], found["facets"]["result"]) == (2, {"Refused": 1, "Failed": 1})
    past = await ask(page=9, pageSize=2)
    # The shared contract answers the last page, with the true total, never an empty one.
    assert ([x["id"] for x in past["data"]], past["pagination"]["page"], past["pagination"]["total"]) == (
        ["call_a1"],
        3,
        5,
    )
