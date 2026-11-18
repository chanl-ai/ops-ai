"""`GET /v1/secrets` a page at a time as a person, by failure mode: another team's or another tenant's secrets on the
page; the team's secrets out of name order; a total that counts rows the page does not hold; a page past the end
answering nothing; `ids` refused on a table keyed by team and name; an account's secret parts missing, which the
pickers read; and names equal ignoring case repeated or lost between pages."""

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


async def test_ids_name_secrets_and_an_accounts_parts_are_listed(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    tenant: str,
) -> None:
    for name in ("BANK_KEY", "CARD_KEY", "LEDGER_KEY"):
        await _made(engine, tenant, TEAM, name)
    with isolation.scope(tenant, TEAM):
        at = datetime.now(UTC)
        await SecretStore(engine).create(tenant, TEAM, "CON_X_KEY", "sealed", actor="t", at=at, connection_id="con_x")
    sam = person(tenant, "Sam Adeyemi", {TEAM: "admin"})
    r = await client.get("/v1/secrets", params={"ids": ["LEDGER_KEY", "CON_X_KEY"]}, headers=sam)
    assert r.status_code == 200, r.text
    listed = [(x["name"], x["connectionId"], x["readOnly"]) for x in r.json()["data"]["data"]]
    assert listed == [("CON_X_KEY", "con_x", True), ("LEDGER_KEY", None, False)]


async def test_names_equal_ignoring_case_each_appear_once_across_pages(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    tenant: str,
) -> None:
    for name in ("Desk_key", "DESK_KEY"):
        await _made(engine, tenant, TEAM, name)
    sam = person(tenant, "Sam Adeyemi", {TEAM: "admin"})
    seen: list[str] = []
    for page_no in (1, 2):
        r = await client.get("/v1/secrets", params={"page": page_no, "pageSize": 1}, headers=sam)
        assert r.status_code == 200, r.text
        seen += [x["name"] for x in r.json()["data"]["data"]]
    assert sorted(seen) == ["DESK_KEY", "Desk_key"]
