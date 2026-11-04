"""The Secrets list holds values tools reference, never a sign-in. Failure modes: the team's own OAuth client secret,
sealed as its app credential's, is listed beside the team's tool secrets, or is rotated there behind the credential's
back. Rig: test_app_accounts."""

from __future__ import annotations

from typing import Any

import httpx

from .test_app_accounts import (
    TEAM,
    World,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_app_credential_create import made
from .test_review_decisions import person


def _data(r: httpx.Response) -> Any:
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


async def test_an_app_credentials_client_secret_is_not_listed_or_rotated_under_secrets(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    row = await made(world, tenant)
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    _data(
        await world.client.post(
            "/v1/secrets", json={"name": "DESK_TOOL_KEY", "value": "x", "teamId": TEAM}, headers=sam
        )
    )

    whole = _data(await world.client.get("/v1/secrets", params={"teamId": TEAM}, headers=sam))
    sealed = [s["name"] for s in whole if s.get("credentialId") == row["id"]]
    assert sealed, "the rig seals the client secret as the team's, under the credential"
    rotated = await world.client.post(
        f"/v1/secrets/{sealed[0]}/rotate", params={"teamId": TEAM}, json={"value": "y"}, headers=sam
    )
    assert rotated.status_code == 409 and rotated.json()["error"]["code"] == "credential_secret", rotated.text

    page = _data(
        await world.client.get("/v1/secrets", params={"teamId": TEAM, "page": 1, "pageSize": 200}, headers=sam)
    )
    names = [s["name"] for s in page["data"]]
    assert "DESK_TOOL_KEY" in names and not set(sealed) & set(names), names
    assert page["pagination"]["total"] == len(names)
