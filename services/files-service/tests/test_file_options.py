"""The file picker's choices (`GET /v1/files/options`, c-159), by failure mode: another team's file offered; a file not
scanned clean offered as choosable; search or paging done on one page instead of in the query; a stored id not
labelled."""

from __future__ import annotations

import sqlalchemy as sa

from ops_files.store import AsyncEngine
from ops_files.store.files import files as files_table

from .test_api import (  # pyright: ignore[reportPrivateUsage]
    OPS,
    PDF,
    Client,
    _data,  # pyright: ignore[reportPrivateUsage]
    client,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_files_page import _stored  # pyright: ignore[reportPrivateUsage]


async def test_options_are_the_teams_files_searched_paged_and_labelled_in_the_query(
    client: Client,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    async with client(admin=True) as c:
        ids = [await _stored(c, f"policy-{i}.pdf", PDF + bytes([i])) for i in range(4)]
        theirs = await _stored(c, "policy-cards.pdf", PDF + b"cards")
        async with engine.begin() as conn:
            await conn.execute(sa.update(files_table).where(files_table.c.id == theirs).values(team="team_cards"))
            await conn.execute(sa.update(files_table).where(files_table.c.id == ids[3]).values(scan_status="pending"))

        first = _data(await c.get("/v1/files/options", params={"search": "POLICY", "limit": 3}, headers=OPS))
        rest = _data(
            await c.get(
                "/v1/files/options", params={"search": "policy", "limit": 3, "cursor": first["nextCursor"]}, headers=OPS
            )
        )
        both = first["data"] + rest["data"]
        assert len(first["data"]) == 3 and rest["nextCursor"] is None, (first, rest)
        assert sorted(o["id"] for o in both) == sorted(ids), both
        assert [o["id"] for o in both if o["disabled"]] == [ids[3]], both

        none = _data(await c.get("/v1/files/options", params={"search": "%"}, headers=OPS))
        labelled = _data(await c.get("/v1/files/options", params=[("ids", ids[0]), ("ids", theirs)], headers=OPS))
        assert none["data"] == [], none
        assert [(o["id"], o["label"]) for o in labelled["data"]] == [(ids[0], "policy-0.pdf")], labelled
