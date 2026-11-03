"""Every table that holds or points at a credential is held by the database (c-616 C5, the proof for C1-C4): another
team or tenant reads none of a row the owner wrote, through any SQL, as the service's own login or as its tenant role
scoped elsewhere; only the service's tenant role, scoped to the row's team or tenant, reads it. The two install tables
(an install's model connections, and model keys spent for many tenants) name no tenant and hold no secret value, so
there is nothing of a tenant's in them to hide; they are checked to stay that way.

Runs on a scratch database of the server OPS_TEST_DATABASE_URL names, with the tools and models chains migrated and
each chain's runtime login made as a deploy makes it (no superuser, no BYPASSRLS); skipped without PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.store import tables as models_tables
from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_tools.store.connections import (
    app_credentials,
    connect_links,
    connection_audit,
    connection_environments,
    connection_tokens,
    connections,
    oauth_states,
)
from ops_tools.store.secrets import secret_audit, tool_secrets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import runtime_role

ROOT = Path(__file__).resolve().parents[3]
PASSWORD = "credential-lock-test"
TEAM_A, TEAM_B = "team_cards", "team_ops"
CONNECTION = "con_lock"
# The thirteen tables of apps.html "Credentials: today and after", by chain and the role its transactions run as.
TOOLS = (
    connection_tokens,
    connection_environments,
    oauth_states,
    connect_links,
    tool_secrets,
    app_credentials,
    connections,
    connection_audit,
    secret_audit,
)
MODELS_LOCKED = (models_tables.provider_keys, models_tables.model_key_tenants)
MODELS_INSTALL = (models_tables.provider_connections, models_tables.model_keys)
ROLES = {"tools": "ops_tools_tenant", "models": "ops_models_tenant"}


def _server() -> URL:
    raw = os.environ.get("OPS_TEST_DATABASE_URL", "")
    if not raw.startswith("postgresql"):
        pytest.skip("the credential lock runs on PostgreSQL; set OPS_TEST_DATABASE_URL")
    return make_url(raw)


async def _admin(url: URL, *statements: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            for s in statements:
                await c.execute(sa.text(s))
    finally:
        await engine.dispose()


def _migrate(url: URL, chain: str) -> None:
    env = {**os.environ, "OPS_DATABASE_URL": url.render_as_string(hide_password=False)}
    done = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        check=False,
        cwd=ROOT / "services" / f"{chain}-service",
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, f"{chain} did not migrate: {done.stderr[-2000:]}"


@pytest.fixture(scope="module")
def scratch() -> Iterator[URL]:
    server = _server()
    url = server.set(database=f"{server.database}_credlock")
    admin = server.set(database="postgres")
    drop = f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'
    asyncio.run(_admin(admin, drop, f'CREATE DATABASE "{url.database}"'))
    try:
        for chain, role in ROLES.items():
            login = runtime_role(chain)
            asyncio.run(
                _admin(
                    admin,
                    f"DO $$ BEGIN CREATE ROLE {login} LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
                    f"ALTER ROLE {login} LOGIN PASSWORD '{PASSWORD}' NOSUPERUSER NOBYPASSRLS INHERIT",
                )
            )
            _migrate(url, chain)
            asyncio.run(
                _admin(
                    url,
                    f"GRANT USAGE ON SCHEMA public TO {login}",
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {login}",
                    f"GRANT {role} TO {login}",
                )
            )
        yield url
    finally:
        asyncio.run(_admin(admin, drop))


def _row(t: sa.Table, tenant: str) -> dict[str, object]:
    """A row of team A in `tenant` with every required column filled from its type."""
    out: dict[str, object] = {}
    for c in t.columns:
        if c.name == "tenant_id":
            out[c.name] = tenant
        elif c.name == "team_id":
            out[c.name] = TEAM_A
        elif c.name == "connection_id" or (t.name == "connections" and c.name == "id"):
            # Every child row hangs off the one connection, which is written first.
            out[c.name] = CONNECTION
        elif (c.autoincrement is True and c.primary_key) or (c.nullable and not c.primary_key):
            continue
        elif isinstance(c.type, sa.DateTime):
            out[c.name] = datetime.now(UTC)
        elif isinstance(c.type, (sa.Integer, sa.Numeric)):
            out[c.name] = 1
        elif isinstance(c.type, sa.Boolean):
            out[c.name] = False
        elif isinstance(c.type, sa.JSON):
            out[c.name] = {}
        else:
            length = getattr(c.type, "length", None) or 32
            out[c.name] = f"x{uuid.uuid4().hex}"[:length]
    return out


async def _seed(url: URL, tenant: str) -> None:
    """One row of team A in every locked table, written as the owner, which row security does not apply to."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as c:
            await c.execute(sa.text("SET LOCAL row_security = off"))
            for t in sorted((*TOOLS, *MODELS_LOCKED), key=lambda t: t is not connections):
                await c.execute(t.insert().values(**_row(t, tenant)))
    finally:
        await engine.dispose()


async def _count(url: URL, login: str, role: str | None, *, tenant: str, team: str | None, table: str) -> int:
    engine = create_async_engine(url.set(username=login, password=PASSWORD))
    try:
        if role is None:
            async with engine.connect() as c:
                return int((await c.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one())
        with isolation.scope(tenant, team):
            async with isolation.isolated_tx(engine, role=role) as c:
                return int((await c.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one())
    finally:
        await engine.dispose()


def test_every_credential_table_is_held_to_its_team_or_tenant_by_the_database(scratch: URL) -> None:
    assert len(TOOLS) + len(MODELS_LOCKED) + len(MODELS_INSTALL) == 13
    unmarked = [t.name for t in (*TOOLS, *MODELS_LOCKED) if isolation_kind(t) not in ("team", "tenant")]
    assert unmarked == [], f"not held by the database: {unmarked}"
    tenant, elsewhere = f"t_{uuid.uuid4().hex[:8]}", f"t_{uuid.uuid4().hex[:8]}"
    asyncio.run(_seed(scratch, tenant))
    for chain, tables in (("tools", TOOLS), ("models", MODELS_LOCKED)):
        login, role = runtime_role(chain), ROLES[chain]
        for t in tables:
            team = TEAM_B if isolation_kind(t) == "team" else None
            leaks = {
                "the login itself": asyncio.run(_count(scratch, login, None, tenant=tenant, team=None, table=t.name)),
                "another team or tenant": asyncio.run(
                    _count(scratch, login, role, tenant=tenant if team else elsewhere, team=team, table=t.name)
                ),
            }
            assert leaks == {"the login itself": 0, "another team or tenant": 0}, (t.name, leaks)
            owner = asyncio.run(_count(scratch, login, role, tenant=tenant, team=TEAM_A, table=t.name))
            assert owner == 1, (t.name, owner)


def test_the_install_tables_hold_no_tenant_and_no_secret_value() -> None:
    for t in MODELS_INSTALL:
        assert isolation_kind(t) == "system", t.name
        names = {c.name for c in t.columns}
        assert not names & {"tenant_id", "team_id", "ciphertext", "secret", "value"}, (t.name, names)
