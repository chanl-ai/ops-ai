"""Secrets managed in one place (c-093), by failure mode: a delete that breaks an operation still naming the secret
(published or staged), a rotation that misses one of the operations reading it, another team's secret of the same name
reaching this team's module (c-509), and a name rule that strands secrets created before it."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_policy import AesGcmCipher, context_of
from ops_service_kit.settings import Settings
from ops_tools.store.secrets import SecretStore

from .conftest import Bank, service_headers
from .test_secrets import MODULE, ROTATED, TEAM, VALUE, keyed  # noqa: F401  # pyright: ignore[reportUnusedImport]

BASE = f"/v1/tool-modules/{MODULE}"


@pytest.fixture
async def k(keyed: Bank) -> Bank:  # noqa: F811
    return keyed


async def _call(bank: Bank, tool: str) -> Any:
    body = {"tool": tool, "input": {}, "key": "s1", "runContext": {"act": "workflow:dispute_email"}}
    return await bank.api.client.post("/v1/calls", json=body, headers=service_headers(bank.api.tenant))


async def _secret(bank: Bank, name: str) -> dict[str, Any]:
    listed = (await bank.api.client.get("/v1/secrets")).json()["data"]
    return next(s for s in listed if s["name"] == name)


async def test_a_secret_lists_the_operations_that_read_it_staged_ones_included(k: Bank) -> None:
    c, tenant = k.api.client, k.api.tenant
    await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    await c.post("/v1/secrets", json={"name": "NEW_KEY", "value": VALUE})
    used = await _secret(k, "BANK_KEY")
    assert [(u["operation"], u["staged"]) for u in used["usedBy"]] == [
        (f"broken_{tenant}", False),
        (f"echo_{tenant}", False),
    ]
    staged = await c.patch(
        f"{BASE}/operations/{MODULE}_op2", json={"headers": [{"key": "X-Api-Key", "value": "{{NEW_KEY}}"}]}
    )
    assert staged.status_code == 200, staged.text
    assert [(u["operation"], u["staged"]) for u in (await _secret(k, "NEW_KEY"))["usedBy"]] == [
        (f"broken_{tenant}", True)
    ]
    # The published operation still reads BANK_KEY until the edit is published, so it still counts.
    assert f"broken_{tenant}" in [u["operation"] for u in (await _secret(k, "BANK_KEY"))["usedBy"]]
    assert VALUE not in (await c.get("/v1/secrets")).text


async def test_a_secret_an_operation_names_cannot_be_deleted(k: Bank) -> None:
    c, tenant = k.api.client, k.api.tenant
    await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    await c.post("/v1/secrets", json={"name": "SPARE_KEY", "value": VALUE})
    refused = await c.delete("/v1/secrets/BANK_KEY")
    error = refused.json()["error"]
    assert refused.status_code == 409 and error["code"] == "secret_in_use", refused.text
    assert sorted(error["details"]["operations"]) == [f"broken_{tenant}", f"echo_{tenant}"]
    assert (await c.delete("/v1/secrets/SPARE_KEY")).status_code == 204
    assert (await _call(k, f"echo_{tenant}")).json()["data"]["output"]["headers"]["x-api-key"] == "[secret]"


async def test_a_rotation_reaches_every_operation_that_reads_it(k: Bank, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    c, tenant = k.api.client, k.api.tenant
    await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    await c.post("/v1/secrets/BANK_KEY/rotate", json={"value": ROTATED})
    for tool in (f"echo_{tenant}", f"broken_{tenant}"):
        out = await _call(k, tool)
        assert k.received[-1]["headers"]["x-api-key"] == ROTATED, tool
        assert ROTATED not in out.text
    assert ROTATED not in caplog.text, "a log line carries the rotated value"


async def test_another_teams_secret_of_the_same_name_is_not_read_and_nothing_is_sent(k: Bank) -> None:
    c, tenant = k.api.client, k.api.tenant
    theirs = await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": "sk-platform", "teamId": "team_platform"})
    assert theirs.status_code == 201 and theirs.json()["data"]["teamId"] == "team_platform", theirs.text
    sent = len(k.received)
    out = (await _call(k, f"echo_{tenant}")).json()["data"]["output"]
    assert out["error"]["code"] == "SECRET_MISSING" and len(k.received) == sent, out
    mine = await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    assert mine.status_code == 201 and mine.json()["data"]["teamId"] == TEAM, mine.text
    assert (await _call(k, f"echo_{tenant}")).status_code == 200 and k.received[-1]["headers"]["x-api-key"] == VALUE


async def test_a_name_made_before_the_64_character_rule_keeps_working(k: Bank, engine: AsyncEngine) -> None:
    """New names stop at 64 characters; one created under the older 120 still resolves and rotates."""
    c, tenant = k.api.client, k.api.tenant
    long = "LEGACY_" + "K" * 73
    assert (await c.post("/v1/secrets", json={"name": long, "value": VALUE})).status_code in (400, 422)
    store = SecretStore(engine)
    # Written as the older rule allowed, with the cipher the app uses (tests/conftest.py build_app).
    blob = AesGcmCipher(Settings().secrets_key.get_secret_value()).encrypt(VALUE, context=context_of(tenant, long))
    assert await store.create(tenant, TEAM, long, blob, actor="before c-093", at=datetime.now(UTC))
    assert (await c.post(f"/v1/secrets/{long}/rotate", json={"value": ROTATED})).status_code == 200
    assert long in [s["name"] for s in (await c.get("/v1/secrets")).json()["data"]]


async def test_an_operation_shows_its_secret_set_only_once_its_own_team_has_it(k: Bank) -> None:
    c = k.api.client
    await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE, "teamId": "team_platform"})
    op = (await c.get(BASE)).json()["data"]["operations"][0]
    assert op["secrets"] == [{"name": "BANK_KEY", "set": False, "available": False}], op["secrets"]
    await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    op = (await c.get(BASE)).json()["data"]["operations"][0]
    assert op["secrets"] == [{"name": "BANK_KEY", "set": True, "available": True}], op["secrets"]
