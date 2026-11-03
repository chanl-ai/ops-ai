"""A write refused because the person it acts for has not connected their own account runs once they have (c-616 S12),
by failure mode: the refusal keeps the write's claim, so the run that waited for them sends the same write under the
same key and gets the refusal replayed, and the write never reaches the system. Rig: test_calls' gateway and fake
bank."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from ops_tools.auth.tokens import Tokens
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore

from .conftest import credentials
from .fake_upstream import ENDPOINT
from .test_calls import MODULE, Gateway, gateway

__all__ = ["gateway"]  # the fixture, used by name

TEAM = "team_platform"
JAMES = "usr_james"


def as_james(tenant: str) -> dict[str, str]:
    """agents-service's token for a run in the module's team, and the person the run acts for, self-signed as a dev
    stack's are."""
    service = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, team_id=TEAM
    )
    claims = {
        "sub": JAMES,
        "email": "j.richardson@bank.test",
        "name": "James Richardson",
        "tenant_id": tenant,
        "team_id": TEAM,
        "kind": "acting_for",
        "act": {"sub": "service:agents"},
        "aud": "tools",
    }
    return {
        "Authorization": f"Bearer {service}",
        "X-Acting-For": mint(claims, dev_service_signer(), ttl_s=TEST_TOKEN_TTL_S),
    }


async def person_key_connection(engine: AsyncEngine, tenant: str) -> str:
    """The bank's module signs in with each person's own API key, and James has given none."""
    store, now, conn = ConnectionStore(engine), datetime.now(UTC), "con_bank_own"
    row: dict[str, Any] = {
        "tenant_id": tenant,
        "id": conn,
        "app_id": conn,
        "team_id": TEAM,
        "name": "Bank",
        "auth_kind": "api_key",
        "sign_in": "person",
        "team_backup": False,
        "status": "healthy",
        "revision": 1,
        "created_by": "t",
        "created_at": now,
        "updated_by": "t",
        "updated_at": now,
    }
    assert await store.create(row, actor="t", at=now)
    plain = {"baseUrl": ENDPOINT, "name": "X-Api-Key"}
    await store.change(tenant, conn, 1, {"settings": plain, "secrets": {}}, actor="t", at=now)
    modules = ModuleStore(engine)
    m = await modules.get(tenant, MODULE)
    assert m is not None
    await modules.put({**m, "connection_id": conn}, expected_revision=m["revision"])
    return conn


async def test_a_write_refused_for_a_missing_account_runs_under_its_key_once_the_person_connects(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    conn = await person_key_connection(engine, tenant)
    args = {"accountId": "CHQ-2219", "hours": 24}
    body = {
        "tool": gateway.tool("place_hold"),
        "input": args,
        "key": "s1",
        "runContext": {"thread": gateway.thread, "step": "s1", "act": "graph", "environment": "test"},
        "approvalToken": gateway.token("place_hold", args, step="s1"),
    }
    first = await gateway.client.post("/v1/calls", json=body, headers=as_james(tenant))
    assert first.status_code == 200, first.text
    assert first.json()["data"]["output"]["error"]["code"] == "CONNECTION_NOT_LINKED", first.text
    assert gateway.received == []
    tokens = Tokens(ConnectionStore(engine), credentials(), None, None)  # pyright: ignore[reportArgumentType]
    await tokens.store_own(tenant, conn, JAMES, {"key": "key-james"})
    again = await gateway.client.post("/v1/calls", json=body, headers=as_james(tenant))
    assert again.status_code == 200 and again.json()["data"]["ok"], again.text
    assert len(gateway.received) == 1, "the write reached the bank once, with James's own key"
