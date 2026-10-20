"""GET /v1/graphs lists what can be run and the input each needs; a picker built on it must not offer a graph
the Runtime cannot run, or leave out one it can."""

from __future__ import annotations

from httpx import AsyncClient


async def test_lists_code_graphs_and_published_definitions_with_their_inputs(client: AsyncClient) -> None:
    rows = (await client.get("/v1/graphs")).json()["data"]
    by_name = {r["name"]: r for r in rows}
    assert {"agent_wrapper", "simple_workflow", "complex_workflow"} <= set(by_name)
    assert [f["name"] for f in by_name["simple_workflow"]["input"]] == ["question"]
    assert by_name["complex_workflow"]["input"][0]["type"] == "email"
    definitions = [r for r in rows if r["kind"] == "definition"]
    assert definitions, "the seeded dispute_email definition is published at start"
    assert all(r["latestVersion"] >= 1 and r["input"][0]["name"] == "email" for r in definitions)
    # A picker shows titles: a built-in graph and a published definition must never read the same.
    titles = [r["title"] for r in rows]
    assert len(titles) == len(set(titles)), titles
    assert all(r["builtIn"] == (r["kind"] == "code") for r in rows)
    # Every listed graph can be started: a thread for each is created without error.
    for name in by_name:
        r = await client.post("/v1/threads", json={"graph": name, "metadata": {}})
        assert r.status_code == 201, (name, r.text)
