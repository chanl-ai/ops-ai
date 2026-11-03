"""A connection's details and its health (c-580), by failure mode: a failing sandbox account's test turns a working
live account to failed, or overwrites the health the live account showed; a connection's category,
description or docs link is lost or takes an address that is not https; the redirect address to register is unknown
until a connection exists."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.connections import SHARED

from .test_connection_test import (  # noqa: F401  # pyright: ignore[reportUnusedImport]
    PRIYA,
    SETTINGS,
    System,
    client,  # pyright: ignore[reportUnusedImport]
    connection,
    system,  # pyright: ignore[reportUnusedImport]
    tokens,
)
from .test_review_decisions import person


async def with_sandbox(client: httpx.AsyncClient, engine: AsyncEngine, tenant: str) -> tuple[str, str]:  # noqa: F811
    """The test connection's own setup as the live account, plus a second account of the app marked sandbox; each
    holds a team sign-in the system answers by its token (at-live, at-sandbox)."""
    live = await connection(client, engine, tenant, SETTINGS)
    made = await client.post(
        f"/v1/apps/{live}/accounts",
        json={"name": "Sandbox", "sandbox": True},
        headers=person(tenant, *PRIYA),
    )
    assert made.status_code == 201, made.text
    sandbox = str(made.json()["data"]["id"])
    put = await client.patch(
        f"/v1/apps/{live}/accounts/{sandbox}",
        json={"revision": made.json()["data"]["revision"], "settings": SETTINGS},
        headers=person(tenant, *PRIYA),
    )
    assert put.status_code == 200, put.text
    for conn, token in ((live, "at-live"), (sandbox, "at-sandbox")):
        await tokens(engine).store_answer(tenant, conn, {"access_token": token, "expires_in": 3600}, SHARED)
    return live, sandbox


async def test_a_failing_sandbox_account_leaves_the_live_accounts_health_and_status_as_they_were(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    system: System,  # noqa: F811
) -> None:
    live, sandbox = await with_sandbox(client, engine, tenant)
    system.answers |= {"at-live": 200, "at-sandbox": 500}
    admin = person(tenant, *PRIYA)
    team = {"account": "team"}
    ok = await client.post(f"/v1/apps/{live}/accounts/{live}/test", json=team, headers=admin)
    assert ok.json()["data"]["status"] == "healthy", ok.text
    before: dict[str, Any] = ok.json()["data"]["health"]
    failed = await client.post(f"/v1/apps/{live}/accounts/{sandbox}/test", json=team, headers=admin)
    assert failed.status_code == 200, failed.text
    assert failed.json()["data"]["health"]["status"] == "failed", failed.text
    after: dict[str, Any] = (await client.get(f"/v1/apps/{live}/accounts/{live}", headers=admin)).json()["data"]
    assert after["status"] == "healthy", "the sandbox account's failure decided the live account's status"
    assert after["health"] == before, "the sandbox account's failure overwrote the live account's health"


async def test_a_connection_keeps_its_category_description_and_docs_link(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    admin = person(tenant, *PRIYA)
    made = await client.post(
        "/v1/apps",
        json={
            "name": "Fraud scores",
            "authKind": "bearer",
            "category": "Risk",
            "description": "A risk score for a transaction or a card.",
            "docsUrl": "https://fraud.example/keys",
        },
        headers=admin,
    )
    assert made.status_code == 201, made.text
    view = made.json()["data"]
    assert (view["category"], view["description"], view["docsUrl"]) == (
        "Risk",
        "A risk score for a transaction or a card.",
        "https://fraud.example/keys",
    )
    changed = await client.patch(
        f"/v1/apps/{view['id']}/accounts/{view['id']}", json={"revision": 1, "category": "Payments"}, headers=admin
    )
    assert changed.json()["data"]["category"] == "Payments", changed.text
    plain = await client.patch(
        f"/v1/apps/{view['id']}/accounts/{view['id']}",
        json={"revision": 2, "docsUrl": "http://fraud.example/keys"},
        headers=admin,
    )
    assert plain.status_code == 400, plain.text


async def test_the_kinds_name_the_redirect_address_before_any_connection_exists(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    kinds = await client.get("/v1/connection-kinds", headers=person(tenant, *PRIYA))
    assert str(kinds.json()["data"].get("redirectUri") or "").endswith("/connections/sign-in/return"), kinds.text
