"""The Secrets list holds values tools reference, never an account's sign-in. Failure mode: the team's own OAuth
client secret, sealed on its account, is listed beside the team's tool secrets. Rig: test_app_accounts."""

from __future__ import annotations

from typing import Any

import httpx

from .test_app_accounts import (
    TEAM,
    World,
    admin,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_app_credential_create import body, on_ops_ais_app
from .test_review_decisions import person


def _data(r: httpx.Response) -> Any:
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


async def test_an_accounts_client_secret_is_not_listed_under_secrets(world: World, tenant: str) -> None:  # noqa: F811
    conn = await on_ops_ais_app(world, tenant)
    _data(await world.client.post("/v1/app-credentials", json=body(), headers=admin(tenant)))
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    _data(
        await world.client.post(
            "/v1/secrets", json={"name": "DESK_TOOL_KEY", "value": "x", "teamId": TEAM}, headers=sam
        )
    )

    whole = _data(await world.client.get("/v1/secrets", params={"teamId": TEAM}, headers=sam))
    sealed = [s["name"] for s in whole if s.get("connectionId") == conn]
    assert sealed, "the rig seals the client secret as the account's secret part"

    page = _data(
        await world.client.get("/v1/secrets", params={"teamId": TEAM, "page": 1, "pageSize": 200}, headers=sam)
    )
    names = [s["name"] for s in page["data"]]
    assert "DESK_TOOL_KEY" in names and not set(sealed) & set(names), names
    assert page["pagination"]["total"] == len(names)
