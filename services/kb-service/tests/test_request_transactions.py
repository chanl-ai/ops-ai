"""When a request holds the database, by failure mode: a route that asks agents-service (who uses a base) while its
transaction is open, so a slow agents-service holds a pooled connection for as long as it takes; a read-only route
opening a transaction for each store call, so one screen's read sees rows from different moments."""

from __future__ import annotations

import json

from ops_kb.agents import StaticAgents, Usage
from ops_kb.store import engine_for
from ops_service_kit.logging import captured_logging
from ops_service_kit.request_timing import current

from .conftest import kb_client


class _NotingAgents(StaticAgents):
    """No agent uses any base; each ask notes how many transactions the request holds open at that moment."""

    def __init__(self) -> None:
        super().__init__()
        self.open_at_call: list[int] = []

    async def usage(self, tenant_id: str, team_id: str | None) -> dict[str, Usage] | None:
        timing = current()
        self.open_at_call.append(timing.db_tx_open if timing is not None else -1)
        return await super().usage(tenant_id, team_id)


async def test_agents_service_is_asked_with_no_transaction_open(database_url: str, tenant: str) -> None:
    engine = engine_for(database_url)
    agents = _NotingAgents()
    try:
        async with kb_client(engine, tenant, agents=agents) as c:
            made = await c.post("/v1/knowledge-bases", json={"name": "Lending", "owner": "maya@harborpine.example"})
            assert made.status_code == 201, made.text
            listed = await c.get("/v1/knowledge-bases")
            one = await c.get(f"/v1/knowledge-bases/{made.json()['data']['id']}")
    finally:
        await engine.dispose()
    assert (listed.status_code, one.status_code) == (200, 200), (listed.text, one.text)
    assert len(agents.open_at_call) == 2, "the list and the detail each ask who uses the base"
    assert set(agents.open_at_call) == {0}, f"agents-service was asked with a transaction open: {agents.open_at_call}"


async def test_a_read_route_reads_in_one_transaction(database_url: str, tenant: str) -> None:
    engine = engine_for(database_url)
    counts: dict[str, int] = {}
    try:
        async with kb_client(engine, tenant) as c:
            made = await c.post("/v1/sources", json={"type": "file", "name": "Policies"})
            assert made.status_code == 201, made.text
            sid = made.json()["data"]["id"]
            for path in (f"/v1/sources/{sid}", "/v1/sources", "/v1/knowledge/lookups"):
                with captured_logging("kb-tx") as stream:
                    r = await c.get(path)
                assert r.status_code == 200, r.text
                line = next(json.loads(x) for x in stream.getvalue().splitlines() if '"http.request"' in x)
                counts[path.replace(sid, "<id>")] = line["db.tx_count"]
    finally:
        await engine.dispose()
    assert counts == {"/v1/sources/<id>": 1, "/v1/sources": 1, "/v1/knowledge/lookups": 1}, counts
