"""An auth config's client secret is changed only through that config. Failure modes: the Secrets list leaves it out,
so a person cannot see where it is kept; it is listed without its config, or as editable; a rotate or delete under
Secrets goes through, or is refused without naming the config. A connection's own secret parts stay off the list.
Rig: test_app_accounts."""

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


async def test_an_auth_configs_client_secret_is_listed_read_only_and_changed_only_on_its_config(
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
    page = _data(
        await world.client.get("/v1/secrets", params={"teamId": TEAM, "page": 1, "pageSize": 200}, headers=sam)
    )
    rows = {s["name"]: s for s in page["data"]}
    sealed = [n for n, s in rows.items() if s.get("credentialId") == row["id"]]
    assert sealed and "DESK_TOOL_KEY" in rows, list(rows)
    assert page["pagination"]["total"] == len(rows)
    owned = rows[sealed[0]]
    assert owned["readOnly"] is True and owned["authConfig"] == {"id": row["id"], "name": row["name"]}, owned
    assert rows["DESK_TOOL_KEY"]["readOnly"] is False and rows["DESK_TOOL_KEY"]["authConfig"] is None
    for method, path, body in (
        ("POST", f"/v1/secrets/{sealed[0]}/rotate", {"value": "y"}),
        ("DELETE", f"/v1/secrets/{sealed[0]}", None),
    ):
        refused = await world.client.request(method, path, params={"teamId": TEAM}, json=body, headers=sam)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "credential_secret", refused.text
        assert row["name"] in refused.json()["error"]["message"], refused.text
