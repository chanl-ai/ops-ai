"""GET /v1/knowledge-bases/options, the agent page's knowledge picker (c-135), by failure mode: a base past the first
hundred not findable; a page that loads every base; the cursor repeating or skipping a base; stored ids not resolving
to their names; another team's base offered."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.store.knowledge import KnowledgeStore

from .conftest import kb_client
from .test_bases_and_sources import data

OPS = {"X-Team-Id": "team_ops"}
LENDING = {"X-Team-Id": "team_lending"}


async def test_options_search_page_resolve_and_scope(
    engine: AsyncEngine, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with kb_client(engine, tenant) as c:
        made = [
            data(await c.post("/v1/knowledge-bases", json={"name": f"Base {i:03d}", "owner": "Ops"}, headers=OPS), 201)
            for i in range(105)
        ]
        theirs = data(
            await c.post("/v1/knowledge-bases", json={"name": "Base lending", "owner": "Lending"}, headers=LENDING), 201
        )

        async def no_whole_table(*_: Any, **__: Any) -> list[dict[str, Any]]:
            raise AssertionError("an options page must not load every base")

        monkeypatch.setattr(KnowledgeStore, "bases", no_whole_table)

        found = data(await c.get("/v1/knowledge-bases/options", params={"search": "base 103"}, headers=OPS))
        assert [o["label"] for o in found["data"]] == ["Base 103"] and found["data"][0]["id"] == made[103]["id"]

        first = data(await c.get("/v1/knowledge-bases/options", params={"search": "base 0", "limit": 60}, headers=OPS))
        assert len(first["data"]) == 60 and first["nextCursor"] == "60"
        rest = data(
            await c.get(
                "/v1/knowledge-bases/options",
                params={"search": "base 0", "limit": 60, "cursor": first["nextCursor"]},
                headers=OPS,
            )
        )
        labels = [o["label"] for o in first["data"] + rest["data"]]
        assert labels == [f"Base {i:03d}" for i in range(100)] and rest["nextCursor"] is None

        ids = [made[104]["id"], theirs["id"], "kb_gone"]
        named = data(await c.get("/v1/knowledge-bases/options", params={"ids": ids}, headers=OPS))
        assert [o["label"] for o in named["data"]] == ["Base 104"], "another team's base and an unknown id are left out"
        lending = data(await c.get("/v1/knowledge-bases/options", params={"search": "base"}, headers=OPS))
        assert all(o["label"] != "Base lending" for o in lending["data"])


async def test_wildcards_in_the_search_match_only_themselves(engine: AsyncEngine, tenant: str) -> None:
    async with kb_client(engine, tenant) as c:
        for n in ("Rate 100%", "Rate 1000", "a_b", "axb"):
            data(await c.post("/v1/knowledge-bases", json={"name": n, "owner": "Ops"}, headers=OPS), 201)
        for term, want in (("100%", ["Rate 100%"]), ("a_b", ["a_b"])):
            got = data(await c.get("/v1/knowledge-bases/options", params={"search": term}, headers=OPS))
            assert [o["label"] for o in got["data"]] == want, term
