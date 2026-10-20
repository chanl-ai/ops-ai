"""What a knowledge base's and a source's detail say the caller may do (c-216), by failure mode: a viewer told it may
edit or delete what its write routes refuse; an admin told it may not; anyone told knowledge publishes."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from .test_bases_and_sources import data
from .test_ownership import _signed_in  # pyright: ignore[reportPrivateUsage]

TEAM = "team_ops"
FLAGS = ("canEdit", "canDelete", "canPublish")


async def test_a_viewer_reads_view_only_and_an_admin_reads_edit_and_delete(engine: AsyncEngine, tenant: str) -> None:
    async with _signed_in(engine, tenant, "james@northfieldbank.com", TEAM, {TEAM: "builder"}) as james:
        kb = data(
            await james.post(
                "/v1/knowledge-bases", json={"name": "Branch manual", "owner": "james@northfieldbank.com"}
            ),
            201,
        )
        src = data(
            await james.post("/v1/sources", json={"type": "file", "name": "Branch PDFs", "collection": "B"}), 201
        )
    for email, role, expected in (
        ("vera@northfieldbank.com", "viewer", (False, False, False)),
        ("priya@northfieldbank.com", "admin", (True, True, False)),
    ):
        async with _signed_in(engine, tenant, email, TEAM, {TEAM: role}) as who:
            base = data(await who.get(f"/v1/knowledge-bases/{kb['id']}"))
            source = data(await who.get(f"/v1/sources/{src['id']}"))
        assert tuple(base[f] for f in FLAGS) == expected, (role, base)
        assert tuple(source[f] for f in FLAGS) == expected, (role, source)
