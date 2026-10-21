"""Who may write knowledge (c-115), by failure mode: a viewer or reviewer creating a knowledge base or a source, a
viewer named as a knowledge base's or source's owner changing it, and a builder of the team refused knowledge someone
else owns (knowledge is shared by the team). Builders and admins of the owning team write;
reviewers decide reviews and viewers read (roles-and-permissions.md), whatever the owner field names. Tokens are
minted and verified as platform-service's are, so the role comes from the token's roles map."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .test_bases_and_sources import data
from .test_ownership import _signed_in  # pyright: ignore[reportPrivateUsage]

TEAM = "team_ops"
RAVI = "ravi@harborpine.example"
SOURCE = {"type": "file", "name": "Branch PDFs", "collection": "Branch"}


@pytest.mark.parametrize("role", ["viewer", "approver"])
async def test_a_viewer_or_reviewer_cannot_create_a_base_or_a_source(
    engine: AsyncEngine, tenant: str, role: str
) -> None:
    base = {"name": f"Branch manual {role}", "owner": RAVI}
    async with _signed_in(engine, tenant, RAVI, TEAM, {TEAM: role}) as ravi:
        for r in (await ravi.post("/v1/knowledge-bases", json=base), await ravi.post("/v1/sources", json=SOURCE)):
            assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", r.text
    # The control: the same bodies from a builder of the team.
    async with _signed_in(engine, tenant, "james@harborpine.example", TEAM, {TEAM: "builder"}) as james:
        data(await james.post("/v1/knowledge-bases", json=base), 201)
        data(await james.post("/v1/sources", json=SOURCE), 201)


async def test_a_viewer_named_as_owner_cannot_change_it(engine: AsyncEngine, tenant: str) -> None:
    async with _signed_in(engine, tenant, "james@harborpine.example", TEAM, {TEAM: "builder"}) as james:
        kb = data(await james.post("/v1/knowledge-bases", json={"name": "Branch manual", "owner": RAVI}), 201)
        src = data(await james.post("/v1/sources", json={**SOURCE, "owner": RAVI}), 201)
    async with _signed_in(engine, tenant, RAVI, TEAM, {TEAM: "viewer"}) as ravi:
        for r in (
            await ravi.patch(f"/v1/knowledge-bases/{kb['id']}", json={"name": "Renamed"}),
            await ravi.post(f"/v1/knowledge-bases/{kb['id']}/sources", json={"sourceIds": [src["id"]]}),
            await ravi.post(f"/v1/sources/{src['id']}/pause"),
            await ravi.patch(f"/v1/sources/{src['id']}", json={"name": "Renamed"}),
            await ravi.delete(f"/v1/sources/{src['id']}"),
            await ravi.delete(f"/v1/knowledge-bases/{kb['id']}"),
        ):
            assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", r.text
    # The control: an admin of the owning team makes the same changes.
    async with _signed_in(engine, tenant, "priya@harborpine.example", TEAM, {TEAM: "admin"}) as priya:
        data(await priya.patch(f"/v1/knowledge-bases/{kb['id']}", json={"name": "Renamed"}))
        data(await priya.post(f"/v1/sources/{src['id']}/pause"))
        assert (await priya.delete(f"/v1/knowledge-bases/{kb['id']}")).status_code == 204


async def test_a_builder_of_the_team_changes_knowledge_someone_else_owns(engine: AsyncEngine, tenant: str) -> None:
    """Knowledge is shared by the team (owner decision, 2026-10-17): the owner field names who answers for it, not who
    may change it. The owner's report: Activate and sync refused a teammate with not_source_owner."""
    nadia = "nadia@harborpine.example"
    async with _signed_in(engine, tenant, nadia, TEAM, {TEAM: "builder"}) as owner:
        kb = data(await owner.post("/v1/knowledge-bases", json={"name": "Nadia's manual", "owner": nadia}), 201)
        src = data(await owner.post("/v1/sources", json={**SOURCE, "owner": nadia}), 201)
    async with _signed_in(engine, tenant, "james@harborpine.example", TEAM, {TEAM: "builder"}) as james:
        data(await james.post(f"/v1/sources/{src['id']}/sync"))
        data(await james.patch(f"/v1/knowledge-bases/{kb['id']}", json={"name": "Branch manual"}))
        data(await james.post(f"/v1/knowledge-bases/{kb['id']}/sources", json={"sourceIds": [src["id"]]}))
        data(await james.post("/v1/sources", json={**SOURCE, "name": "Linked", "kbIds": [kb["id"]]}), 201)
        assert (await james.delete(f"/v1/sources/{src['id']}")).status_code == 204
