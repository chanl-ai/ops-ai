"""platform-service on the compose PostgreSQL (`make db-up`), migrated by its own chain, each test on fresh tenants."""

from __future__ import annotations

import hashlib
import html
import os
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_email import MemorySender
from ops_identity import ServiceAuth, mint_service_token
from ops_platform.api.app import create_internal_app, create_public_app
from ops_platform.keys import dev_signer
from ops_platform.signin_options import SignInOptions
from ops_platform.store.identity import IdentityStore
from ops_platform.store.roles import ensure_builtin_roles, mirror_membership
from ops_platform.store.tables import api_keys, members, role_assignments, teams, tenants, users
from ops_policy import Ed25519Signer
from ops_service_kit.contract import response_checker
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import isolate_from_stack, refusal
from ops_signin.dns import TxtResolver
from ops_signin.fake_idp import FakeDns, self_signed
from ops_signin.fake_idp import create_app as create_idp

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
    isolate_from_stack()
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
        """A user in a tenant (new unless given) with one team per role, written as the superuser, with the built-in
        role assignments the member routes would have written."""
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
                await ensure_builtin_roles(c, tenant, at=now)
            await c.execute(
                users.insert().values(
                    id=user, tenant_id=tenant, email=address, name="Ana Ops", status="active", created_at=now
                )
            )
            for role in roles:
                team = new_id("team")
                await c.execute(
                    teams.insert().values(
                        id=team,
                        tenant_id=tenant,
                        name=f"Team {role} {team}",
                        owner_groups=[],
                        scope="owned",
                        created_at=now,
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
                await mirror_membership(
                    c,
                    tenant_id=tenant,
                    team_id=team,
                    user_id=user,
                    member_role=role,
                    security_team="team_security",
                    granted_by="test",
                    at=now,
                )
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
    internal = create_internal_app(store, services=SERVICES, signer=signer)
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


# ── Sign-in providers (c-188): the public app with a fake identity provider, a mail sender that keeps what it sends,
# and one tenant whose Security team admin configures its providers ──

IDP = "http://idp.test"
CONSOLE = "http://console.test"
PUBLIC_URL = "http://platform"
OIDC_SECRET = "bank-oidc"
# The SAML service provider's key pair every rig's platform-service holds (c-197).
SP_KEY, SP_CERT = self_signed("sp")


@dataclass
class Round:
    """One SSO round trip: where the provider's answer sent the browser, the console query, and the completion."""

    location: str
    query: dict[str, str]
    flow_key: str
    completed: httpx.Response | None


@dataclass
class SignInRig:
    public: httpx.AsyncClient
    idp: httpx.AsyncClient
    mail: MemorySender
    engine: AsyncEngine
    tenant: str
    security_team: str
    ops_team: str
    admin: dict[str, str]
    app: FastAPI
    # A domain of this run's own: email domains are unique across tenants, and the test database outlives a run.
    zone: str = field(default_factory=lambda: f"{secrets.token_hex(4)}.bank.test")

    async def person(self, email: str, *, role: str = "viewer", tenant: str | None = None) -> str:
        """A person in the rig's tenant (or `tenant`), a member of a new team with `role`."""
        now = now_iso()
        tenant = tenant or self.tenant
        user, team = new_id("usr"), new_id("team")
        async with self.engine.begin() as c:
            await c.execute(
                users.insert().values(
                    id=user, tenant_id=tenant, email=email, name=email, status="active", created_at=now
                )
            )
            await c.execute(
                teams.insert().values(
                    id=team, tenant_id=tenant, name=f"T {team}", owner_groups=[], scope="owned", created_at=now
                )
            )
            await c.execute(
                members.insert().values(
                    id=new_id("mem"), tenant_id=tenant, team_id=team, user_id=user, email=email, role=role,
                    status="active", created_at=now, updated_at=now,
                )
            )  # fmt: skip
            await mirror_membership(
                c, tenant_id=tenant, team_id=team, user_id=user, member_role=role, security_team=self.security_team,
                granted_by="test", at=now,
            )  # fmt: skip
        return user

    async def security_admin_only(self, email: str) -> dict[str, str]:
        """Headers of an admin of the Security team who holds no role in every team: settings.manage, but not a
        workspace admin."""
        user, now = new_id("usr"), now_iso()
        async with self.engine.begin() as c:
            await c.execute(
                users.insert().values(
                    id=user, tenant_id=self.tenant, email=email, name="S", status="active", created_at=now
                )
            )
            await c.execute(
                members.insert().values(
                    id=new_id("mem"), tenant_id=self.tenant, team_id=self.security_team, user_id=user, email=email,
                    role="admin", status="active", created_at=now, updated_at=now,
                )
            )  # fmt: skip
            await mirror_membership(
                c, tenant_id=self.tenant, team_id=self.security_team, user_id=user, member_role="admin",
                security_team=self.security_team, granted_by="test", at=now,
            )  # fmt: skip
        r = await self.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
        return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": self.security_team}

    async def configure(
        self, provider_id: str, body: dict[str, Any], *, headers: dict[str, str] | None = None, verify: bool = True
    ) -> httpx.Response:
        """Saves a provider and, with `verify`, proves each of its new domains the way a bank would: publishes the
        claim's TXT record at the fake DNS and asks platform-service to check it (c-195)."""
        r = await self.public.put(
            f"/v1/settings/sign-in/providers/{provider_id}", json=body, headers=headers or self.admin
        )
        if verify and r.status_code == 200:
            for check in r.json()["data"]["verification"]:
                if check["verifiedAt"] is None:
                    await self.verify_domain(check["domain"], check["record"]["value"], headers=headers)
        return r

    async def publish_txt(self, domain: str, *values: str) -> None:
        assert (await self.idp.put(f"/dns/txt/{domain}", json={"values": list(values)})).status_code == 200

    async def verify_domain(
        self, domain: str, value: str | None = None, *, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """Publishes `value` (when given) as the domain's TXT record, then asks platform-service to verify it."""
        if value is not None:
            await self.publish_txt(domain, value)
        r = await self.public.post(f"/v1/settings/sign-in/domains/{domain}/verify", headers=headers or self.admin)
        assert value is None or r.status_code == 200, r.text
        return r

    async def oidc(self, domain: str, *, name: str = "bank", jit: bool = True, enabled: bool = True) -> str:
        provider = new_id("sip")
        body: dict[str, Any] = {
            "kind": "oidc",
            "label": "Bank SSO",
            "enabled": enabled,
            "domains": [domain],
            "oidc": {"issuer": f"{IDP}/oidc/{name}", "clientId": "ops-console", "clientSecretRef": OIDC_SECRET},
        }
        if jit:
            body["jit"] = {"team": self.ops_team, "role": "chat_user"}
        r = await self.configure(provider, body)
        assert r.status_code == 200, r.text
        return provider

    async def saml(self, domain: str, *, name: str = "bank") -> str:
        provider = new_id("sip")
        cert = (await self.idp.get(f"/saml/{name}/certificate")).text
        body = {
            "kind": "saml",
            "label": "Bank SAML",
            "domains": [domain],
            "saml": {"idpEntityId": f"{IDP}/saml/{name}", "ssoUrl": f"{IDP}/saml/{name}/sso", "certificate": cert},
            "jit": {"team": self.ops_team, "role": "chat_user"},
        }
        r = await self.configure(provider, body)
        assert r.status_code == 200, r.text
        return provider

    async def answer(self, redirect_url: str, *, user: str, stale: bool = False, idp_path: str | None = None) -> str:
        """Signs `user` in at the identity provider and hands its answer to platform-service; returns the console URL
        platform-service sent the browser to. `idp_path` sends the request to another provider than the one asked."""
        url = httpx.URL(redirect_url)
        params = dict(url.params) | {"user": user} | ({"stale": "1"} if stale else {})
        at_idp = await self.idp.get(idp_path or url.path, params=params)
        if at_idp.status_code == 302:
            back = httpx.URL(at_idp.headers["location"])
            r = await self.public.get(back.path, params=dict(back.params))
        else:
            form = dict(re.findall(r'name="(\w+)" value="([^"]*)"', at_idp.text))
            form = {k: html.unescape(v) for k, v in form.items()}
            r = await self.public.post(
                "/v1/auth/saml/acs",
                content=urlencode(form),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        assert r.status_code == 303, r.text
        return r.headers["location"]

    async def sign_in_sso(self, email: str, *, user: str | None = None, stale: bool = False) -> Round:
        r = await self.public.post("/v1/auth/sso/start", json={"email": email})
        assert r.status_code == 200, r.text
        start = r.json()["data"]
        location = await self.answer(start["redirectUrl"], user=user or email, stale=stale)
        query = dict(httpx.URL(location).params)
        completed = None
        if "code" in query:
            completed = await self.public.post(
                "/v1/auth/sso/complete", json={"code": query["code"], "flowKey": start["flowKey"]}
            )
        return Round(location, query, start["flowKey"], completed)


@pytest.fixture
async def signin(engine: AsyncEngine, database_url: str) -> AsyncIterator[SignInRig]:
    security, ops, tenant = new_id("team"), new_id("team"), new_id("ten")
    store = IdentityStore.open(database_url)
    mail = MemorySender()
    fake_dns = FakeDns()
    dns_port, stop_dns = fake_dns.serve()
    options = SignInOptions(
        password_iterations=1_000,
        password_min_length=12,
        flow_ttl_s=600,
        reset_ttl_s=3600,
        public_url=PUBLIC_URL,
        console_url=CONSOLE,
        secrets={OIDC_SECRET: SecretStr("s3cret")},
        mail=mail,
        transport=httpx.ASGITransport(app=create_idp(IDP, fake_dns)),
        dns=TxtResolver([f"127.0.0.1:{dns_port}"], timeout_s=2),
        saml_sp_key=SecretStr(SP_KEY),
        saml_sp_certificate=SP_CERT,
    )
    public = create_public_app(
        store,
        dev_signer(),
        demo_password=DEMO_PASSWORD,
        audiences=["platform", "agents"],
        security_team=security,
        signin=options,
    )
    now = now_iso()
    admin_email = f"{new_id('sec')}@bank.test"
    async with engine.begin() as c:
        await c.execute(
            tenants.insert().values(id=tenant, name=tenant, status="active", allowed_domains=[], created_at=now)
        )
        await ensure_builtin_roles(c, tenant, at=now)
        admin = new_id("usr")
        await c.execute(
            users.insert().values(
                id=admin, tenant_id=tenant, email=admin_email, name="Sam", status="active", created_at=now
            )
        )
        for team in (security, ops):
            await c.execute(
                teams.insert().values(
                    id=team, tenant_id=tenant, name=team, owner_groups=[], scope="owned", created_at=now
                )
            )
            await c.execute(
                members.insert().values(
                    id=new_id("mem"), tenant_id=tenant, team_id=team, user_id=admin, email=admin_email, role="admin",
                    status="active", created_at=now, updated_at=now,
                )
            )  # fmt: skip
            await mirror_membership(
                c, tenant_id=tenant, team_id=team, user_id=admin, member_role="admin", security_team=security,
                granted_by="test", at=now,
            )  # fmt: skip
        # The rig's admin is also a workspace admin: Admin in every team (c-198).
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"), tenant_id=tenant, subject_kind="person", subject_id=admin, role_id="admin",
                team_id="*", granted_by="test", reason="workspace admin", source="grant", created_at=now,
            )
        )  # fmt: skip
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=public),
            base_url=PUBLIC_URL,
            event_hooks={"response": [response_checker(public)]},
        ) as pub,
        httpx.AsyncClient(transport=options.transport, base_url=IDP) as idp,
    ):
        r = await pub.post("/v1/auth/sign-in", json={"email": admin_email, "password": DEMO_PASSWORD})
        token = r.json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}", "X-Team-Id": security}
        yield SignInRig(pub, idp, mail, engine, tenant, security, ops, headers, public)
    stop_dns.set()
    await store.close()
