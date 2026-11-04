"""tools_0062 turns each connection's slots into accounts, by failure mode: a connection with both slots loses its Test
slot, or its sandbox keeps secret rows that still name the old connection, so deleting either strands them; a
Test-only connection becomes a live account a production run would sign in with; a plugin's account loses the app it
belongs to; a token sealed with its slot survives and fails to open; and the downgrade leaves a sandbox account where
the Test slot was."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .test_registry_store import _alembic, scratch_database  # pyright: ignore[reportPrivateUsage]

BEFORE = "tools_0061_app_credentials"
AFTER = "tools_0062_accounts"
T = "t_acc"


async def _sql(engine: AsyncEngine, statement: str, **values: Any) -> None:
    async with engine.begin() as c:
        await c.execute(sa.text(statement), values)


async def _connection(engine: AsyncEngine, cid: str, slots: dict[str, dict[str, Any]], plugin: str | None) -> None:
    at = datetime.now(UTC)
    await _sql(
        engine,
        "insert into connections (tenant_id, id, team_id, name, auth_kind, status, revision, created_by, created_at, "
        "updated_by, updated_at, plugin_id, account_name) values (:t, :id, 'team_a', :id, 'api_key', 'healthy', 3, "
        "'p', :at, 'p', :at, :plugin, :account)",
        t=T, id=cid, at=at, plugin=plugin, account=f"{cid} account" if plugin else None,
    )  # fmt: skip
    for env, slot in slots.items():
        await _sql(
            engine,
            "insert into connection_environments (tenant_id, connection_id, environment, team_id, settings, secrets, "
            "credential_id, updated_by, updated_at) values (:t, :id, :env, 'team_a', cast(:s as json), "
            "cast(:x as json), :cred, 'p', :at)",
            t=T, id=cid, env=env, s=json.dumps(slot["settings"]), x=json.dumps(slot.get("secrets", {})),
            cred=slot.get("credential"), at=at,
        )  # fmt: skip
        for name in slot.get("secrets", {}).values():
            await _secret(engine, name, cid)
        await _sql(
            engine,
            "insert into connection_tokens (tenant_id, connection_id, environment, team_id, person_id, access_ct, "
            "scopes, rotations, refreshed_at) values (:t, :id, :env, 'team_a', '', 'sealed', cast('[]' as json), 0, "
            ":at)",
            t=T, id=cid, env=env, at=at,
        )  # fmt: skip


async def _secret(engine: AsyncEngine, name: str, cid: str) -> None:
    await _sql(
        engine,
        "insert into tool_secrets (tenant_id, team_id, name, ciphertext, version, created_by, created_at, "
        "connection_id) values (:t, 'team_a', :n, 'sealed', 1, 'p', :at, :id)",
        t=T, n=name, at=datetime.now(UTC), id=cid,
    )  # fmt: skip


async def _rows(engine: AsyncEngine, query: str) -> list[dict[str, Any]]:
    async with engine.connect() as c:
        return [dict(r) for r in (await c.execute(sa.text(query))).mappings()]


async def test_tools_0062_makes_one_account_per_slot_and_folds_them_back() -> None:
    async with scratch_database("tools_accounts") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _connection(engine, "con_live", {"production": {"settings": {"baseUrl": "https://live.test"}}}, None)
            await _connection(
                engine, "con_trial", {"test": {"settings": {"baseUrl": "https://trial.test"}}}, "desk"
            )  # fmt: skip
            await _sql(
                engine,
                "insert into app_credentials (tenant_id, id, team_id, app_id, client_id, secret_name, created_by, "
                "created_at, updated_by, updated_at) values (:t, 'cred_uat', 'team_a', 'desk', 'uat-app', "
                "'CRED_UAT_SECRET', 'p', :at, 'p', :at)",
                t=T, at=datetime.now(UTC),
            )  # fmt: skip
            await _secret(engine, "CRED_UAT_SECRET", "con_both")
            await _connection(
                engine,
                "con_both",
                {
                    "production": {"settings": {"baseUrl": "https://prod.test"}, "secrets": {"key": "K_PROD"}},
                    "test": {
                        "settings": {"baseUrl": "https://uat.test"}, "secrets": {"key": "K_TEST"},
                        "credential": "cred_uat",
                    },
                },
                "desk",
            )  # fmt: skip
            _alembic(target, "upgrade", AFTER)
            accounts = {
                r["id"]: r
                for r in await _rows(
                    engine,
                    "select id, name, account_name, sandbox, app_id, settings, secrets, credential_id, "
                    "revision from connections order by id",
                )
            }
            assert set(accounts) == {"con_live", "con_trial", "con_both", "con_both_sandbox"}, accounts
            live, trial, both, sandbox = (
                accounts[k] for k in ("con_live", "con_trial", "con_both", "con_both_sandbox")
            )
            assert (live["sandbox"], live["app_id"], live["settings"]) == (
                False, "con_live", {"baseUrl": "https://live.test"}
            )  # fmt: skip
            assert (trial["sandbox"], trial["app_id"]) == (True, "plugin:desk"), (
                "a Test-only slot became a live account"
            )
            assert (both["sandbox"], both["settings"], both["secrets"]) == (
                False, {"baseUrl": "https://prod.test"}, {"key": "K_PROD"}
            )  # fmt: skip
            assert sandbox["sandbox"] is True and sandbox["app_id"] == "plugin:desk", sandbox
            assert (sandbox["name"], sandbox["account_name"]) == ("con_both sandbox", "con_both account sandbox")
            assert (sandbox["settings"], sandbox["secrets"], sandbox["credential_id"]) == (
                {"baseUrl": "https://uat.test"}, {"key": "K_TEST"}, "cred_uat"
            )  # fmt: skip
            owners = {
                r["name"]: r["connection_id"]
                for r in await _rows(engine, "select name, connection_id from tool_secrets")
            }
            assert owners == {
                "K_PROD": "con_both", "K_TEST": "con_both_sandbox", "CRED_UAT_SECRET": "con_both_sandbox"
            }, owners  # fmt: skip
            creds = await _rows(engine, "select app_id from app_credentials")
            assert creds == [{"app_id": "plugin:desk"}], creds
            assert await _rows(engine, "select connection_id from connection_tokens") == [], "a sealed token survived"
            _alembic(target, "downgrade", BEFORE)
            slots = [
                (r["connection_id"], r["environment"], r["settings"])
                for r in await _rows(
                    engine, "select connection_id, environment, settings from connection_environments order by 1, 2"
                )
            ]
            assert slots == [
                ("con_both", "production", {"baseUrl": "https://prod.test"}),
                ("con_both", "test", {"baseUrl": "https://uat.test"}),
                ("con_live", "production", {"baseUrl": "https://live.test"}),
                ("con_trial", "test", {"baseUrl": "https://trial.test"}),
            ], slots
            ids = [r["id"] for r in await _rows(engine, "select id from connections order by id")]
            assert ids == ["con_both", "con_live", "con_trial"], "the split sandbox stayed after the downgrade"
            back = {
                r["name"]: r["connection_id"]
                for r in await _rows(engine, "select name, connection_id from tool_secrets")
            }
            assert back["K_TEST"] == "con_both" and back["CRED_UAT_SECRET"] == "con_both", back
            plugins = {r["id"]: r["plugin_id"] for r in await _rows(engine, "select id, plugin_id from connections")}
            assert plugins == {"con_both": "desk", "con_live": None, "con_trial": "desk"}, plugins
        finally:
            await engine.dispose()


def _json(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(value) if isinstance(value, str) else value)


async def test_tools_0063_drops_the_slot_name_from_an_accounts_health() -> None:
    # Health carried its slot's name onto the account, and the app page's model refuses the key: the page answered 500.
    async with scratch_database("tools_health") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _connection(engine, "con_hub", {"production": {"settings": {"baseUrl": "https://hub.test"}}}, "hub")
            health = {"status": "ok", "account": "team", "environment": "production", "at": "2026-11-01T10:00:00Z"}
            await _sql(
                engine,
                "update connection_environments set health = cast(:h as json) where connection_id = 'con_hub'",
                h=json.dumps(health),
            )
            _alembic(target, "upgrade", "tools_0063_health_slot")
            [row] = await _rows(engine, "select health from connections where id = 'con_hub'")
            kept = _json(row["health"])
            assert kept == {"status": "ok", "account": "team", "at": "2026-11-01T10:00:00Z"}, kept
            _alembic(target, "downgrade", AFTER)
            [row] = await _rows(engine, "select health from connections where id = 'con_hub'")
            back = _json(row["health"])
            assert back == health, back
        finally:
            await engine.dispose()
