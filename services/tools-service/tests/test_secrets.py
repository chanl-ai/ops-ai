"""Tool secrets: a value goes in and never comes out, is resolved only when a call runs, takes effect on the next
call after a rotation, and appears in no response, call log row, error or log line, even when the upstream echoes
it back. Every create, rotate, delete and use is audited."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_tools.modules.seed import blank
from ops_tools.store.calls import gateway_calls
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.secrets import SecretStore, tool_secrets

from .conftest import Bank, service_headers
from .fake_upstream import ENDPOINT, HOST

VALUE = "sk-live-7f3c9e1d2b"
ROTATED = "sk-live-rotated-55a1"
MODULE = "mod_keyed"


async def _keyed_module(engine: AsyncEngine, tenant: str) -> None:
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    m = blank(
        module_id=MODULE,
        tenant_id=tenant,
        team_id="team_platform",
        owner="Platform",
        me="James Richardson",
        at=datetime.now(UTC),
        input={"displayName": "Keyed", "name": "keyed", "type": "http"},
    )
    header = [{"key": "X-Api-Key", "value": "{{BANK_KEY}}"}]

    def op(n: int, name: str, path: str) -> dict[str, Any]:
        return {
            "id": f"{MODULE}_op{n}", "tool_id": f"tl_{name}", "name": name, "description": name, "access": "read",
            "enabled": True, "executor": "http", "method": "GET", "path": path, "headers": header, "body": None,
            "input": [], "masked_output": [], "binding": None, "rate_limit_per_min": 60, "requires_approval": False,
            "amount_max": None, "stub": {},
        }  # fmt: skip

    m.update(
        status="published",
        endpoint=ENDPOINT,
        egress_hosts=[HOST],
        operations=[op(1, f"echo_{tenant}", "/echo-headers"), op(2, f"broken_{tenant}", "/broken")],
    )
    await ModuleStore(engine).put(m, expected_revision=None)


async def _call(bank: Bank, tool: str) -> Any:
    body = {"tool": tool, "input": {}, "key": "s1", "runContext": {"act": "workflow:dispute_email"}}
    return await bank.api.client.post("/v1/calls", json=body, headers=service_headers(bank.api.tenant))


@pytest.fixture
async def keyed(bank: Bank, engine: AsyncEngine) -> Bank:
    await _keyed_module(engine, bank.api.tenant)
    return bank


async def test_a_value_goes_in_and_never_comes_out(keyed: Bank) -> None:
    c = keyed.api.client
    made = await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    assert made.status_code == 201, made.text
    listed = await c.get("/v1/secrets")
    assert [s["name"] for s in listed.json()["data"]] == ["BANK_KEY"]
    rotated = await c.post("/v1/secrets/BANK_KEY/rotate", json={"value": ROTATED})
    assert rotated.json()["data"]["version"] == 2
    for r in (made, listed, rotated):
        assert VALUE not in r.text and ROTATED not in r.text
    taken = await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": "other"})
    assert taken.status_code == 409


async def test_a_rotation_reaches_the_next_call(keyed: Bank) -> None:
    await keyed.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    await _call(keyed, f"echo_{keyed.api.tenant}")
    assert keyed.received[-1]["headers"]["x-api-key"] == VALUE
    await keyed.api.client.post("/v1/secrets/BANK_KEY/rotate", json={"value": ROTATED})
    await _call(keyed, f"echo_{keyed.api.tenant}")
    assert keyed.received[-1]["headers"]["x-api-key"] == ROTATED


async def test_no_value_reaches_a_response_the_call_log_an_error_or_a_log_line(
    keyed: Bank, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    tenant = keyed.api.tenant
    await keyed.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    echoed = await _call(keyed, f"echo_{tenant}")
    assert echoed.json()["data"]["output"]["headers"]["x-api-key"] == "[secret]", "the upstream echoed it back"
    failed = await _call(keyed, f"broken_{tenant}")
    executions = await keyed.api.client.get("/v1/executions", params={"pageSize": 50})
    async with engine.connect() as c:
        rows = (await c.execute(gateway_calls.select().where(gateway_calls.c.tool.like(f"%_{tenant}")))).mappings()
        logged = json.dumps([dict(r) for r in rows], default=str)
    for text in (echoed.text, failed.text, executions.text, logged, caplog.text):
        assert VALUE not in text


async def test_a_missing_or_misplaced_secret_sends_nothing(keyed: Bank, engine: AsyncEngine) -> None:
    tenant = keyed.api.tenant
    missing = await _call(keyed, f"echo_{tenant}")
    assert missing.json()["data"]["output"]["error"]["code"] == "SECRET_MISSING"
    await keyed.api.client.post("/v1/secrets", json={"name": "OTHER_KEY", "value": VALUE})
    # Another secret's ciphertext moved under this name fails to decrypt: the name is bound into the encryption.
    async with engine.begin() as c:
        blob = (
            await c.execute(
                sa.select(tool_secrets.c.ciphertext).where(
                    tool_secrets.c.name == "OTHER_KEY", tool_secrets.c.tenant_id == tenant
                )
            )
        ).scalar_one()
        await c.execute(
            tool_secrets.insert().values(
                tenant_id=tenant,
                name="BANK_KEY",
                ciphertext=blob,
                version=1,
                created_by="x",
                created_at=datetime.now(UTC),
            )
        )
    moved = await _call(keyed, f"echo_{tenant}")
    assert moved.json()["data"]["output"]["error"]["code"] == "SECRET_MISSING"
    assert not [x for x in keyed.received if x["path"] == "/v1/echo-headers"]


async def test_every_create_rotate_delete_and_use_is_audited(keyed: Bank, engine: AsyncEngine) -> None:
    c = keyed.api.client
    await c.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    await _call(keyed, f"echo_{keyed.api.tenant}")
    await c.post("/v1/secrets/BANK_KEY/rotate", json={"value": ROTATED})
    gone = await c.delete("/v1/secrets/BANK_KEY")
    assert gone.status_code == 204
    trail = [(a["action"], a["version"], a["tool"]) for a in await SecretStore(engine).audit(keyed.api.tenant)]
    assert trail == [
        ("created", 1, None),
        ("used", 1, f"echo_{keyed.api.tenant}"),
        ("rotated", 2, None),
        ("deleted", 2, None),
    ]


def test_the_dev_key_is_refused_outside_dev() -> None:
    with pytest.raises(ValueError, match="secrets_key must be set outside dev"):
        Settings(
            environment="production",
            auth_mode="platform",
            review_key=SecretStr("r" * 40),
        )
    with pytest.raises(ValueError, match="64 hex"):
        Settings(secrets_key=SecretStr("not-hex"))
