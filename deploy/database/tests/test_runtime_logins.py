"""Each service that switches roles per transaction (SET LOCAL ROLE) works as its own deployed login: no superuser, no
BYPASSRLS, and a member of a role only once an install script or a migration made it one (c-444). On a scratch
database the files and documents chains migrate; each login starts as staging's did, made by a roles.sql older than
the roles; then one path that grants membership runs alone: the chains' own migrations, or grants.sql as make db-ddl
writes it. After it, the login runs a team transaction as its tenant role and the outbox relay as its system role.

Runs on the server of OPS_TEST_DATABASE_URL (make python-verify sets it); skipped without a PostgreSQL URL. Roles are
cluster-wide, so each case revokes the logins' memberships before it starts."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_documents.store.document_types import document_types
from ops_documents.store.extractions import service_outbox as documents_outbox
from ops_documents.store.metadata import ROLE as DOCUMENTS_ROLE
from ops_documents.store.metadata import SYSTEM_ROLE as DOCUMENTS_SYSTEM
from ops_files.store import files as files_store
from ops_store import isolation
from ops_store.outbox import Relay, add

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postgres import Postgres
from schema import OFFLINE_URL, memberships, runtime_role

ROOT = Path(__file__).resolve().parents[3]
PASSWORD = "runtime-login-test"


@dataclass(frozen=True)
class Service:
    chain: str
    tenant_role: str
    system_role: str
    outbox: sa.Table
    team_table: sa.Table

    @property
    def login(self) -> str:
        return runtime_role(self.chain)


SERVICES = [
    Service("files", files_store.ROLE, files_store.SYSTEM_ROLE, files_store.service_outbox, files_store.files),
    Service("documents", DOCUMENTS_ROLE, DOCUMENTS_SYSTEM, documents_outbox, document_types),
]


def _server() -> URL:
    raw = os.environ.get("OPS_TEST_DATABASE_URL", "")
    if not raw.startswith("postgresql"):
        pytest.skip("runtime logins run on PostgreSQL; set OPS_TEST_DATABASE_URL")
    return make_url(raw)


async def _admin(url: URL, *statements: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            for s in statements:
                await c.execute(sa.text(s))
    finally:
        await engine.dispose()


def _as_staging_made_it(scratch: URL) -> None:
    """Each login as a roles.sql older than files_0011 left it: a non-superuser login with its tables and no roles."""
    for s in SERVICES:
        statements = [
            f"DO $$ BEGIN CREATE ROLE {s.login} LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
            f"ALTER ROLE {s.login} LOGIN PASSWORD '{PASSWORD}' NOSUPERUSER NOBYPASSRLS INHERIT",
            f"REVOKE {s.tenant_role}, {s.system_role} FROM {s.login}",
        ]
        asyncio.run(_admin(scratch.set(database="postgres"), *statements))
        asyncio.run(
            _admin(
                scratch,
                f"GRANT USAGE ON SCHEMA public TO {s.login}",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {s.login}",
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {s.login}",
            )
        )


def _migrate(scratch: URL, chain: str, target: str = "head", *, how: str = "upgrade") -> None:
    env = {**os.environ, "OPS_DATABASE_URL": scratch.render_as_string(hide_password=False)}
    done = subprocess.run(
        ["uv", "run", "alembic", how, target],
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
    url = server.set(database=f"{server.database}_logins")
    drop = f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'
    admin = server.set(database="postgres")
    asyncio.run(_admin(admin, drop))
    asyncio.run(_admin(admin, f'CREATE DATABASE "{url.database}"'))
    try:
        for s in SERVICES:
            _migrate(url, s.chain)
        yield url
    finally:
        asyncio.run(_admin(admin, drop))


async def _works_as_its_login(scratch: URL, s: Service) -> None:
    """A team transaction writes an event as the tenant role; the relay delivers it as the system role."""
    engine = create_async_engine(scratch.set(username=s.login, password=PASSWORD))
    sent: list[dict[str, Any]] = []

    async def send(event: dict[str, Any]) -> None:
        sent.append(event)

    tenant = f"t_{uuid.uuid4().hex[:10]}"
    try:
        async with engine.connect() as c:
            flags = (
                await c.execute(sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))
            ).one()
        assert tuple(flags) == (False, False)
        with isolation.scope(tenant, "team_a"):
            async with isolation.isolated_tx(engine, role=s.tenant_role) as c:
                await c.execute(sa.select(sa.func.count()).select_from(s.team_table))
                await add(c, s.outbox, tenant_id=tenant, team_id="team_a", name="login.checked", key=tenant, payload={})
        assert await Relay(engine, s.outbox, send, role=s.system_role).once() >= 1
        assert tenant in {e["tenantId"] for e in sent}
    finally:
        await engine.dispose()


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s.chain)
def test_the_chain_s_migrations_make_its_login_a_member(scratch: URL, service: Service) -> None:
    """Staging: a login made before the roles existed; the release command migrates as the superuser."""
    _as_staging_made_it(scratch)
    # Back to the revision that made the roles, then forward again as a release command would.
    _migrate(scratch, service.chain, f"{service.chain}_0011", how="downgrade")
    _migrate(scratch, service.chain, "head")
    asyncio.run(_works_as_its_login(scratch, service))


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s.chain)
def test_grants_sql_makes_each_login_a_member_of_the_roles_its_tables_grant_to(scratch: URL, service: Service) -> None:
    """Every deploy applies grants.sql; it repairs a login whatever roles.sql it was made by."""
    _as_staging_made_it(scratch)
    pg = Postgres(_server().set(database="postgres").render_as_string(hide_password=False))
    url = scratch.render_as_string(hide_password=False)
    dump = pg.dump_schema(url)
    tables = {s.chain: [t.name for t in s.outbox.metadata.sorted_tables] for s in SERVICES}
    runtime = {s.chain: s.login for s in SERVICES}
    granted = pg.roles(url, {g for e in dump.entries for g in pg.grantees(e)})
    members = memberships(pg, dump.entries, runtime=runtime, tables=tables, sequences={}, roles=set(granted))
    assert members[service.login] == {service.tenant_role, service.system_role}
    pg.execute(url, pg.grants_script(runtime, tables, {}, {}, members))
    asyncio.run(_works_as_its_login(scratch, service))


@pytest.mark.parametrize("chain", [s.chain for s in SERVICES])
def test_a_dba_upgrade_grants_the_membership_in_the_superuser_script(chain: str) -> None:
    """The DBA runs upgrade.sql as the migrator, who may not grant a role: the step's grants go to upgrade-roles.sql."""
    env = {**os.environ, "OPS_DATABASE_URL": OFFLINE_URL}
    done = subprocess.run(
        ["uv", "run", "alembic", "upgrade", f"{chain}_0011:{chain}_0012", "--sql"],
        check=False,
        cwd=ROOT / "services" / f"{chain}-service",
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    body, moved = Postgres.superuser_statements(done.stdout)
    login = runtime_role(chain)
    assert sorted(m.split(" THEN ")[1].split(";")[0] for m in moved) == [
        f"GRANT ops_{chain}_system TO {login}",
        f"GRANT ops_{chain}_tenant TO {login}",
    ]
    assert f"TO {login}" not in body
