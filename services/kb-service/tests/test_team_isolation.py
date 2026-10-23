"""A knowledge base is its team's (c-407): a person outside the owning team does not see it in the list, and reading it
or its documents by id answers 404. By failure mode, with tokens minted as platform-service mints them: the list
shows another team's base; a read by id answers 200; a sub-route answers 200."""

from __future__ import annotations

from typing import Any

import httpx

from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint

from .test_ownership import PLATFORM
from .test_provisioned_bases import kb  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture


def outsider(tenant: str) -> dict[str, str]:
    """An admin of team_lending only, in the same tenant as team_ops."""
    claims = {
        "sub": "usr_omar",
        "email": "omar@harborpine.example",
        "name": "omar",
        "kind": "person",
        "aud": ["kb"],
        "tenant_id": tenant,
        "team_ids": ["team_lending"],
        "roles": {"team_lending": "admin"},
        "auth_method": "session",
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_lending"}


async def _base(kb: httpx.AsyncClient) -> dict[str, Any]:  # noqa: F811
    made = await kb.post("/v1/knowledge-bases", json={"name": "Dispute handbook", "owner": "Card operations"})
    assert made.status_code == 201, made.text
    return made.json()["data"]


async def test_the_list_leaves_out_another_teams_base(kb: httpx.AsyncClient, tenant: str) -> None:  # noqa: F811
    base = await _base(kb)
    mine = (await kb.get("/v1/knowledge-bases")).json()["data"]["data"]
    assert base["id"] in [b["id"] for b in mine]
    theirs = (await kb.get("/v1/knowledge-bases", headers=outsider(tenant))).json()["data"]["data"]
    assert base["id"] not in [b["id"] for b in theirs]


async def test_another_teams_base_answers_404_by_id(kb: httpx.AsyncClient, tenant: str) -> None:  # noqa: F811
    base = await _base(kb)
    assert (await kb.get(f"/v1/knowledge-bases/{base['id']}")).status_code == 200
    r = await kb.get(f"/v1/knowledge-bases/{base['id']}", headers=outsider(tenant))
    assert r.status_code == 404, r.text


async def test_another_teams_base_documents_answer_404(kb: httpx.AsyncClient, tenant: str) -> None:  # noqa: F811
    base = await _base(kb)
    assert (await kb.get(f"/v1/knowledge-bases/{base['id']}/documents")).status_code == 200
    r = await kb.get(f"/v1/knowledge-bases/{base['id']}/documents", headers=outsider(tenant))
    assert r.status_code == 404, r.text


async def test_a_name_is_unique_in_a_team_and_another_teams_id_is_refused_unnamed(
    kb: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    """A base's name is unique in its team, and a team never sees another's (c-507): another team may use the name. An
    id is unique in the tenant, so another team's is refused with 409 and no owner named, never a 500."""
    base = await _base(kb)
    again = {"name": "Dispute handbook", "owner": "Lending"}
    assert (await kb.post("/v1/knowledge-bases", json=again)).status_code == 409, "the same team's name is taken"
    r = await kb.post("/v1/knowledge-bases", json=again, headers=outsider(tenant))
    assert r.status_code == 201, r.text
    same_id = {"id": base["id"], "name": "Another handbook", "owner": "Lending"}
    r = await kb.post("/v1/knowledge-bases", json=same_id, headers=outsider(tenant))
    assert r.status_code == 409 and "team_" not in r.text, r.text
