"""A connection's details and its health per environment (c-580), by failure mode: a failing sandbox test turns a
working production connection to failed, or overwrites the health production showed; a connection's category,
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


async def with_production(client: httpx.AsyncClient, engine: AsyncEngine, tenant: str) -> str:  # noqa: F811
    """The test connection's own setup, plus a production environment whose team sign-in the system accepts."""
    conn = await connection(client, engine, tenant, SETTINGS)
    put = await client.put(
        f"/v1/connections/{conn}/environments/production",
        json={"revision": 2, "settings": {**SETTINGS, "baseUrl": "https://crm.bank.test"}},
        headers=person(tenant, *PRIYA),
    )
    assert put.status_code == 200, put.text
    answer = {"access_token": "at-prod", "expires_in": 3600}
    await tokens(engine).store_answer(tenant, conn, "production", answer, SHARED)
    return conn


async def test_a_failing_sandbox_leaves_a_working_production_connection_as_it_was(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    system: System,  # noqa: F811
) -> None:
    conn = await with_production(client, engine, tenant)
    system.answers |= {"at-prod": 200, "at-team": 500}
    admin = person(tenant, *PRIYA)
    team = {"account": "team"}
    ok = await client.post(f"/v1/connections/{conn}/test", json={"environment": "production", **team}, headers=admin)
    assert ok.json()["data"]["status"] == "healthy", ok.text
    failed = await client.post(f"/v1/connections/{conn}/test", json={"environment": "test", **team}, headers=admin)
    view: dict[str, Any] = failed.json()["data"]
    assert view["status"] == "healthy", "the sandbox's failure decided a connection that has production"
    assert view["environments"]["test"]["health"]["status"] == "failed"
    assert view["environments"]["production"]["health"]["status"] == "ok"
    assert view["health"]["environment"] == "production", "the old field stopped meaning production's result"


async def test_a_connection_keeps_its_category_description_and_docs_link(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    admin = person(tenant, *PRIYA)
    made = await client.post(
        "/v1/connections",
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
        f"/v1/connections/{view['id']}", json={"revision": 1, "category": "Payments"}, headers=admin
    )
    assert changed.json()["data"]["category"] == "Payments", changed.text
    plain = await client.patch(
        f"/v1/connections/{view['id']}", json={"revision": 2, "docsUrl": "http://fraud.example/keys"}, headers=admin
    )
    assert plain.status_code == 400, plain.text


async def test_the_kinds_name_the_redirect_address_before_any_connection_exists(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    kinds = await client.get("/v1/connection-kinds", headers=person(tenant, *PRIYA))
    assert str(kinds.json()["data"].get("redirectUri") or "").endswith("/connections/sign-in/return"), kinds.text
