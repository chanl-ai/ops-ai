"""platform-service on the compose PostgreSQL (`make db-up`), migrated by its own chain, each test on fresh tenants."""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_identity import ServiceAuth, mint_service_token
from ops_platform.api.app import create_internal_app, create_public_app
from ops_platform.keys import dev_signer
from ops_platform.store.identity import IdentityStore
from ops_platform.store.tables import api_keys, members, teams, tenants, users
from ops_policy import Ed25519Signer
from ops_service_kit.contract import response_checker
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import refusal

ROOT = Path(__file__).parents[1]
DEMO_PASSWORD = "demo-password-for-tests"
# The calling service's own key, trusted by the internal app for that service only (I13).
CALLER = Ed25519Signer.generate("svc-agents-1")
SERVICES = ServiceAuth(
    audience="platform", verifiers={CALLER.kid: (CALLER.verifier("platform"), "agents")}, tenant_scoped=False
)
SERVICE_TOKEN = mint_service_token(CALLER, service="agents", audience="platform", tenant_id=None, ttl_s=3600)
SERVICE = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


def pytest_configure(config: pytest.Config) -> None:
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)


def alembic_config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture(scope="session")
def database_url() -> str:
    command.upgrade(alembic_config(), "head")
    return Settings().database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@dataclass
class Person:
    tenant_id: str
    user_id: str
    email: str
    teams: dict[str, str] = field(default_factory=dict[str, str])  # team id -> role


@dataclass
class Platform:
    public: httpx.AsyncClient
    internal: httpx.AsyncClient
    engine: AsyncEngine
    signer: Ed25519Signer
    store: IdentityStore
    public_app: FastAPI
    internal_app: FastAPI

    async def person(
        self, *, roles: tuple[str, ...] = ("admin",), email: str | None = None, tenant_id: str | None = None
    ) -> Person:
        """A user in a tenant (new unless given) with one team per role, written as the superuser."""
        now = now_iso()
        tenant = tenant_id or new_id("ten")
        user = new_id("usr")
        address = email or f"{user}@bank.test"
        p = Person(tenant, user, address)
        async with self.engine.begin() as c:
            if tenant_id is None:
                await c.execute(
                    tenants.insert().values(id=tenant, name=tenant, status="active", allowed_domains=[], created_at=now)
                )
            await c.execute(
                users.insert().values(
                    id=user, tenant_id=tenant, email=address, name="Ana Ops", status="active", created_at=now
                )
            )
            for role in roles:
                team = new_id("team")
                await c.execute(
                    teams.insert().values(
                        id=team, tenant_id=tenant, name=f"Team {role}", owner_groups=[], scope="owned", created_at=now
                    )
                )
                await c.execute(
                    members.insert().values(
                        id=new_id("mem"),
                        tenant_id=tenant,
                        team_id=team,
                        user_id=user,
                        email=address,
                        role=role,
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
                p.teams[team] = role
        return p

    async def api_key(self, p: Person, *, scopes: tuple[str, ...] = ("read",), **state: str) -> str:
        """A key bound to the person's first team; returns the full `ok_<id>.<secret>` text."""
        key_id, secret = new_id("key"), new_id("sec")
        async with self.engine.begin() as c:
            await c.execute(
                api_keys.insert().values(
                    id=key_id,
                    tenant_id=p.tenant_id,
                    team_id=next(iter(p.teams)),
                    name="ci",
                    prefix=key_id,
                    secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
                    scopes=list(scopes),
                    created_by=p.user_id,
                    created_at=now_iso(),
                    **state,
                )
            )
        return f"ok_{key_id}.{secret}"

    async def sign_in(self, p: Person, password: str = DEMO_PASSWORD) -> httpx.Response:
        return await self.public.post("/v1/auth/sign-in", json={"email": p.email, "password": password})


@pytest.fixture
async def platform(engine: AsyncEngine, database_url: str) -> AsyncIterator[Platform]:
    store = IdentityStore.open(database_url)
    signer = dev_signer()
    public = create_public_app(store, signer, demo_password=DEMO_PASSWORD, audiences=["platform", "agents"])
    internal = create_internal_app(store, services=SERVICES)
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=public),
            base_url="http://platform",
            event_hooks={"response": [response_checker(public)]},
        ) as pub,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=internal),
            base_url="http://platform-internal",
            event_hooks={"response": [response_checker(internal)]},
        ) as inner,
    ):
        yield Platform(pub, inner, engine, signer, store, public, internal)
    await store.close()
