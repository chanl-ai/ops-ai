"""A person's connectors (GET /v1/me/connections), by failure mode: two accounts of one app come back as two rows; the
row names a tool the team has not switched on, or a write without its reviewed mark; the row's account is not the one
the sign-in named; the call count holds another person's calls, the team account's, last month's or a refused one; an
app the install no longer loads is offered; and an app the team has off is missing, so the person cannot ask for it."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import sqlalchemy as sa

from ops_store import isolation
from ops_tools.auth.tokens import Tokens
from ops_tools.connectors import _reviewed, can_do  # pyright: ignore[reportPrivateUsage]
from ops_tools.store.calls import gateway_calls
from ops_tools.store.connections import ConnectionStore

from .conftest import credentials
from .test_plugin_manifest_fields import (  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures
    TEAM,
    TokenDesk,
    admin,
    desk_rig,  # pyright: ignore[reportUnusedImport]
    turn_on,
)
from .test_review_decisions import person

SITES = "plugin:test.fields-sites"
PRIYA = "usr_priya"


def id_token(email: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{body}.sig"


async def _sites_on(c: httpx.AsyncClient, tenant: str) -> str:
    on = await turn_on(c, tenant, "test.fields-sites", client=("multi-app", "app-secret"))
    assert on.status_code == 200, on.text
    return str(on.json()["data"]["connectionId"])


async def _second(c: httpx.AsyncClient, tenant: str, first: str) -> str:
    page = (await c.get(f"/v1/apps/{SITES}", headers=admin(tenant))).json()["data"]
    credential = page["card"]["credential"]["id"] if page["card"].get("credential") else None
    made = await c.post(
        f"/v1/apps/{SITES}/accounts", json={"name": "Sites · second org", "credentialId": credential},
        headers=admin(tenant),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    assert made.json()["data"]["id"] != first
    return str(made.json()["data"]["id"])


async def _signed_in(store: ConnectionStore, tenant: str, conn: str, email: str) -> None:
    answer = {"access_token": f"at-{uuid4().hex[:6]}", "expires_in": 3600, "id_token": id_token(email)}
    await Tokens(store, credentials(), None, None).store_answer(tenant, conn, answer, PRIYA)


async def _mine(c: httpx.AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    got = await c.get("/v1/me/connections", headers=headers)
    assert got.status_code == 200, got.text
    return list(got.json()["data"])


async def test_two_accounts_of_one_app_are_one_row_named_as_the_sign_in_said(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, store, _), _ = desk_rig
    first = await _sites_on(c, tenant)
    second = await _second(c, tenant, first)
    await _signed_in(store, tenant, first, "priya@live.example")
    await _signed_in(store, tenant, second, "priya@second.example")
    rows = [r for r in await _mine(c, admin(tenant)) if r["appId"] == SITES]
    assert len(rows) == 1, rows
    row = rows[0]
    assert (row["appState"], row["accountCount"], row["primaryAccountId"]) == ("connected", 2, first), row
    assert row["account"] == "priya@live.example" and row["inChat"] is True, row
    assert {a["account"] for a in row["accounts"]} == {"priya@live.example", "priya@second.example"}, row
    # Two connected and none saved: no account is her default yet, so a call asks which.
    assert not any(a["primary"] for a in row["accounts"]), row["accounts"]
    pinned = await c.put(f"/v1/apps/{SITES}/accounts/{second}/default", headers=admin(tenant))
    assert pinned.status_code == 200, pinned.text
    row = next(r for r in await _mine(c, admin(tenant)) if r["appId"] == SITES)
    assert (row["primaryAccountId"], row["account"]) == (second, "priya@second.example"), row
    assert {a["connectionId"]: a["primary"] for a in row["accounts"]} == {first: False, second: True}, row["accounts"]


async def test_the_line_names_only_switched_on_tools(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, store, _), _ = desk_rig
    first = await _sites_on(c, tenant)
    await _signed_in(store, tenant, first, "priya@live.example")
    row = next(r for r in await _mine(c, admin(tenant)) if r["appId"] == SITES)
    # A new app starts with every tool on; a tool switched off leaves the line.
    # No team policy reader in this rig: only a tool's own setting marks a write reviewed (the next test covers that).
    assert row["canDo"] == "Reads: Read a record · Writes: Change a record", row["canDo"]
    removed = await c.delete(f"/v1/apps/{SITES}/tools/fields_sites_update_record", headers=admin(tenant))
    assert removed.status_code == 200, removed.text
    row = next(r for r in await _mine(c, admin(tenant)) if r["appId"] == SITES)
    assert [t["title"] for t in row["tools"]] == ["Read a record"], row["tools"]
    assert row["canDo"] == "Reads: Read a record", row["canDo"]


async def test_a_write_the_teams_policy_holds_is_marked_reviewed() -> None:
    module = {"id": "mod_plugin_sites", "template_id": "plugin:test.fields-sites"}

    class Listed:
        async def levels(self, tenant_id: str, team_id: str | None) -> dict[str, Any]:
            return {}

        async def answer(
            self, tenant_id: str, team_id: str | None, mod: dict[str, Any] | None, **kw: Any
        ) -> dict[str, Any]:
            # The gateway's rule is held by tools-service; here the team's policy holds this app's writes.
            return {"waits": kw["access"] != "read" and mod is not None}

    class Modules:
        async def get(self, tenant_id: str, module_id: str) -> dict[str, Any]:
            return module

    apps: Any = SimpleNamespace(write_approvals=Listed(), modules=Modules())
    who: Any = SimpleNamespace(tenant_id="t", team=SimpleNamespace(id=TEAM))
    tools = [
        {"name": "r", "title": "Read a record", "access": "read", "waits": False, "moduleId": module["id"]},
        {"name": "w", "title": "Change a record", "access": "write", "waits": False, "moduleId": module["id"]},
    ]
    marked = await _reviewed(apps, who, tools)
    assert [t["reviewed"] for t in marked] == [False, True], marked
    assert can_do(marked) == "Reads: Read a record · Writes, reviewed first: Change a record"
    apps.write_approvals = None
    assert [t["reviewed"] for t in await _reviewed(apps, who, tools)] == [False, False]


async def test_the_call_count_is_the_callers_own_this_week(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, store, _), _ = desk_rig
    first = await _sites_on(c, tenant)
    await _signed_in(store, tenant, first, "priya@live.example")
    now = datetime.now(UTC)
    rows = [
        ("priya@bank.example", now - timedelta(hours=1), "ok"),
        ("priya@bank.example", now - timedelta(hours=3), "refused"),
        ("priya@bank.example", now - timedelta(days=2), "error"),
        ("priya@bank.example", now - timedelta(days=8), "ok"),
        ("maya@bank.example", now - timedelta(hours=1), "ok"),
        (None, now - timedelta(hours=1), "ok"),
    ]
    async with store.engine.begin() as conn:
        for who, at, outcome in rows:
            await conn.execute(
                sa.insert(gateway_calls).values(
                    id=f"call_{uuid4().hex[:10]}", tool="fields_sites_get_record", access="read", input_hash="h",
                    idempotency_key=uuid4().hex, sub="s", decision="allow", reasons=[], approvers=[],
                    outcome=outcome, effect=False, effect_scope="none", created_at=at.isoformat(),
                    module_id="mod_plugin_fields_sites", tenant_id=tenant, team_id=TEAM, acting_for=who,
                )
            )  # fmt: skip
    row = next(r for r in await _mine(c, admin(tenant)) if r["appId"] == SITES)
    assert row["used"]["callsThisWeek"] == 2, row["used"]


async def test_an_app_off_for_the_team_is_listed_off_and_one_the_install_lacks_is_not(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, store, _), _ = desk_rig
    await _sites_on(c, tenant)
    # An account left behind by a plugin this install no longer loads, which the person once signed in to.
    now = datetime.now(UTC)
    row = {
        "tenant_id": tenant, "id": "con_gone", "app_id": "plugin:test.gone", "team_id": TEAM, "name": "Gone desk",
        "auth_kind": "oauth2_auth_code", "sign_in": "person", "status": "healthy", "revision": 1,
        "created_by": "t", "created_at": now, "updated_by": "t", "updated_at": now,
    }  # fmt: skip
    with isolation.scope(tenant, TEAM):
        assert await store.create(row, actor="t", at=now)
        await Tokens(store, credentials(), None, None).store_answer(tenant, "con_gone", {"access_token": "at-x"}, PRIYA)
    listed = await c.get("/v1/me/accounts?every=true", headers=admin(tenant))
    assert any(a["appId"] == "plugin:test.gone" for a in listed.json()["data"]), listed.text
    assert all(r["appId"] != "plugin:test.gone" for r in await _mine(c, admin(tenant)))

    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    rows = {r["appId"]: r for r in await _mine(c, sam)}
    off = rows.get(SITES)
    # Security has no auth config for the app and this install has no app of its own for it, so it reads that.
    assert off is not None and off["appState"] == "needs_auth_config" and off["accounts"] == [], rows
    assert off["mayManage"] is True and off["inChat"] is False and off["canDo"] == "Reads: Read a record", off
    # The team-only desk acts as the team, never as a person, so it is no connector of Sam's.
    assert "plugin:test.fields" not in rows, rows
    viewer = person(tenant, "Ravi Menon", {"team_security": "viewer"})
    assert next(r for r in await _mine(c, viewer) if r["appId"] == SITES)["mayManage"] is False


async def test_an_apps_card_says_the_callers_own_sign_in_beside_the_teams(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, store, _), _ = desk_rig
    first = await _sites_on(c, tenant)
    viewer = person(tenant, "Ravi Menon", {TEAM: "viewer"})

    async def own(headers: dict[str, str]) -> str | None:
        cards = (await c.get("/v1/apps", headers=headers)).json()["data"]
        return next(x for x in cards if x["id"] == SITES).get("ownSignIn")

    assert await own(viewer) == "none"
    await _signed_in(store, tenant, first, "priya@live.example")
    assert await own(admin(tenant)) == "connected" and await own(viewer) == "none"
