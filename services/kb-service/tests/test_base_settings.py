"""A knowledge base's settings, by failure mode: a save of one section that resets the others, a field the base no
longer keeps (or never had) saved as if it worked, and a preset that leaves a section unset or outlives a change."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from .test_bases_and_sources import data

SECTIONS = ("retrieval", "answer", "sync", "access", "sourceDefaults")


async def base(client: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    body = {"name": "Card disputes", "owner": "maya@harborpine.example", **extra}
    return data(await client.post("/v1/knowledge-bases", json=body), 201)


async def test_a_patch_of_one_section_keeps_the_others(client: httpx.AsyncClient) -> None:
    kb = await base(client)
    patch = {
        "answer": {"shape": "chunks"},
        "sync": {"changes": "review", "staleAfterDays": 90},
        "access": {"mcp": {"enabled": True, "toolName": "search_disputes"}},
        "sourceDefaults": {"size": 300, "overlap": 30},
    }
    data(await client.patch(f"/v1/knowledge-bases/{kb['id']}", json=patch))
    data(await client.patch(f"/v1/knowledge-bases/{kb['id']}", json={"retrieval": {"chunkLimit": 4}}))
    got = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))
    assert got["retrieval"]["chunkLimit"] == 4 and got["retrieval"]["threshold"] == kb["retrieval"]["threshold"]
    assert got["answer"] == {**kb["answer"], "shape": "chunks"}
    assert got["sync"] == {**kb["sync"], "changes": "review", "staleAfterDays": 90}
    assert got["access"]["mcp"] == {"enabled": True, "toolName": "search_disputes"}
    assert got["access"]["members"] == {"mode": "all", "principals": []}
    assert got["sourceDefaults"] == {**kb["sourceDefaults"], "size": 300, "overlap": 30}
    assert got["automation"] == "suggest"


@pytest.mark.parametrize(
    "patch",
    [
        {"retrieval": {"model": "bank-standard"}},
        {"retrieval": {"citationStyle": "inline"}},
        {"answer": {"temperature": 0.2}},
        {"sync": {"everyHours": 6}},
        {"access": {"members": {"mode": "selected", "principals": ["usr_1"]}}},
        {"sourceDefaults": {"strategies": ["structure", "faq"]}},
    ],
)
async def test_an_unknown_or_dropped_field_is_refused(client: httpx.AsyncClient, patch: dict[str, Any]) -> None:
    kb = await base(client)
    r = await client.patch(f"/v1/knowledge-bases/{kb['id']}", json=patch)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_settings", r.text
    assert data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))["retrieval"] == kb["retrieval"]


async def test_a_preset_fills_every_section_and_a_later_patch_wins(client: httpx.AsyncClient) -> None:
    raw = await base(client, name="Rate tables", preset="raw")
    precise = await base(client, name="Fee schedules", preset="precise")
    for kb in (raw, precise):
        assert all(kb[s] for s in SECTIONS), kb
        assert "answerShape" not in kb["retrieval"] and "model" not in kb["retrieval"]
    assert (raw["answer"]["shape"], precise["answer"]["shape"]) == ("chunks", "answer_with_citations")
    assert (raw["retrieval"]["chunkLimit"], precise["retrieval"]["chunkLimit"]) == (10, 5)
    assert precise["sourceDefaults"]["strategies"] == ["structure", "context_headers"]
    patched = data(
        await client.patch(
            f"/v1/knowledge-bases/{raw['id']}",
            json={"answer": {"shape": "answer_with_citations"}, "retrieval": {"chunkLimit": 3}},
        )
    )
    assert (patched["answer"]["shape"], patched["retrieval"]["chunkLimit"]) == ("answer_with_citations", 3)
    listed = {b["id"]: b for b in data(await client.get("/v1/knowledge-bases"))["data"]}
    assert listed[raw["id"]]["answer"]["shape"] == "answer_with_citations"
