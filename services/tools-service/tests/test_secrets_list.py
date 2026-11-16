"""`GET /v1/secrets` a page at a time as a person, by failure mode: another team's or another tenant's secrets on the
page; the team's secrets out of name order; a total that counts rows the page does not hold; a page past the end
answering nothing."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_tools.store.secrets import SecretStore

from . import test_egress_and_secrets_need_security_admin as security_admin
from .test_review_decisions import person

# The service as the security tests build it, with signed person tokens.
client = security_admin.client

TEAM = "team_security"


async def _made(engine: AsyncEngine, tenant: str, team: str, name: str) -> None:
    with isolation.scope(tenant, team):
        await SecretStore(engine).create(tenant, team, name, f"sealed-{name}", actor="seed", at=datetime.now(UTC))


async def test_the_list_holds_the_acting_teams_secrets_only_in_name_order(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    tenant: str,
) -> None:
    for name in ("LEDGER_KEY", "BANK_KEY", "CARD_KEY"):
        await _made(engine, tenant, TEAM, name)
    await _made(engine, tenant, "team_ops", "AARDVARK_KEY")
    await _made(engine, f"{tenant}_other", TEAM, "ARREARS_KEY")
    sam = person(tenant, "Sam Adeyemi", {TEAM: "admin", "team_ops": "admin"})
    r = await client.get("/v1/secrets", params={"page": 1, "pageSize": 5}, headers=sam)
    assert r.status_code == 200, r.text
    page = r.json()["data"]
    assert [(x["teamId"], x["name"]) for x in page["data"]] == [
        (TEAM, "BANK_KEY"),
        (TEAM, "CARD_KEY"),
        (TEAM, "LEDGER_KEY"),
    ]
    assert page["pagination"]["total"] == 3


async def test_a_page_past_the_end_answers_the_last_page(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    tenant: str,
) -> None:
    for name in ("PAST_A", "PAST_B", "PAST_C"):
        await _made(engine, tenant, TEAM, name)
    sam = person(tenant, "Sam Adeyemi", {TEAM: "admin"})
    r = await client.get("/v1/secrets", params={"search": "past_", "page": 9, "pageSize": 2}, headers=sam)
    assert r.status_code == 200, r.text
    page = r.json()["data"]
    assert [x["name"] for x in page["data"]] == ["PAST_C"]
    assert (page["pagination"]["page"], page["pagination"]["total"]) == (2, 3)
