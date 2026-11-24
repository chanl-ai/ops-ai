"""An S3 account's typed address, by failure mode: Test connection sends a request (and the signed key) to an address
on a host the tenant has not listed, and the test of an account on a listed host goes out unsigned, which every S3
store refuses."""

from __future__ import annotations

import httpx

from .test_connection_test import (  # noqa: F401  # pyright: ignore[reportUnusedImport]
    PRIYA,
    System,
    client,  # pyright: ignore[reportUnusedImport]
    system,  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

ENDPOINT = "https://s3.eu-west-9.storage.test"


async def s3_account(client: httpx.AsyncClient, tenant: str) -> str:  # noqa: F811
    admin = person(tenant, *PRIYA)
    made = await client.post("/v1/apps", json={"name": "Claims archive", "authKind": "aws_sigv4"}, headers=admin)
    assert made.status_code == 201, made.text
    conn = str(made.json()["data"]["id"])
    body = {
        "revision": 1,
        "settings": {"baseUrl": ENDPOINT, "accessKeyId": "AKIATEST", "region": "eu-west-9", "testPath": "/"},
        "secretValues": {"secretAccessKey": "s3-secret-9d1c"},
    }
    put = await client.patch(f"/v1/apps/{conn}/accounts/{conn}", json=body, headers=admin)
    assert put.status_code == 200, put.text
    return conn


async def test_an_endpoint_on_an_unlisted_host_is_held_and_no_call_leaves(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
    system: System,  # noqa: F811
) -> None:
    conn = await s3_account(client, tenant)
    admin = person(tenant, *PRIYA)
    held = await client.post(f"/v1/apps/{conn}/accounts/{conn}/test", json={"account": "team"}, headers=admin)
    assert held.status_code == 200, held.text
    health = held.json()["data"]["health"]
    assert health["status"] == "failed" and "s3.eu-west-9.storage.test" in health["message"], health
    assert system.seen == [], "a request left for a host the tenant never listed"
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    await client.post("/v1/egress/hosts", json={"value": "s3.eu-west-9.storage.test"}, headers=security)
    sent = await client.post(f"/v1/apps/{conn}/accounts/{conn}/test", json={"account": "team"}, headers=admin)
    assert sent.status_code == 200, sent.text
    assert len(system.seen) == 1 and system.seen[0].startswith("AWS4-HMAC-SHA256 Credential=AKIATEST/"), system.seen
    assert "s3-secret-9d1c" not in sent.text
