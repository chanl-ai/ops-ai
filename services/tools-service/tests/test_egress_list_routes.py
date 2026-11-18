"""The egress lists through their routes, by failure mode: another tenant's hosts or ranges shown, or counted in a
list's total."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from .test_egress_and_secrets_need_security_admin import client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person


def _data(r: httpx.Response) -> Any:
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


async def test_another_tenants_hosts_and_ranges_never_appear(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    other = f"t_{uuid4().hex[:10]}"
    mine, theirs = (
        person(tenant, "Sam Adeyemi", {"team_security": "admin"}),
        person(other, "Ana Ruiz", {"team_security": "admin"}),
    )
    for who, host, cidr in (
        (mine, "isol-mine.example.com", "10.61.0.0/16"),
        (theirs, "isol-theirs.example.com", "10.62.0.0/16"),
    ):
        _data(await client.post("/v1/egress/hosts", json={"value": host}, headers=who))
        _data(await client.post("/v1/egress/ranges", json={"value": cidr}, headers=who))

    whole = _data(await client.get("/v1/egress", headers=mine))
    assert [h["host"] for h in whole["hosts"] if h["host"].startswith("isol-")] == ["isol-mine.example.com"]
    assert [x["cidr"] for x in whole["ranges"] if x["cidr"].startswith("10.6")] == ["10.61.0.0/16"]
    page = _data(await client.get("/v1/egress/hosts", params={"search": "isol-"}, headers=mine))
    assert [h["host"] for h in page["data"]] == ["isol-mine.example.com"]
    assert page["pagination"]["total"] == 1
