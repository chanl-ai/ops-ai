"""platform-service as deployed: connected as a login role that owns no table, is not a superuser and does not bypass
row-level security. The compose user is a superuser, so every other test would pass even if the lookups that come
before a tenant is known (email, session, key prefix, invite token) found nothing for a real deployment."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_platform.api.app import create_internal_app, create_public_app
from ops_platform.keys import dev_signer
from ops_platform.signin_options import SignInOptions
from ops_platform.store.identity import IdentityStore
from ops_platform.store.tables import users
from ops_platform.store.tenancy import ROLE, TenantDb

from .conftest import CONSOLE, DEMO_PASSWORD, OIDC_SECRET, PUBLIC_URL, SERVICE, SERVICES, Platform, SignInRig

APP_ROLE = "ops_platform_app_test"


@pytest.fixture
async def app_url(engine: AsyncEngine, database_url: str) -> AsyncIterator[str]:
    """A login role like a deployment's: a member of the tenant role and nothing more."""
    async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as c:
        exists = (await c.execute(sa.text("select 1 from pg_roles where rolname = :r"), {"r": APP_ROLE})).first()
        if exists is None:
            await c.execute(sa.text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD 'app' NOSUPERUSER NOBYPASSRLS NOINHERIT"))
        await c.execute(sa.text(f"GRANT {ROLE} TO {APP_ROLE}"))
        flags = (
            await c.execute(sa.text("select rolsuper, rolbypassrls from pg_roles where rolname = :r"), {"r": APP_ROLE})
        ).one()
    assert tuple(flags) == (False, False)
    yield make_url(database_url).set(username=APP_ROLE, password="app").render_as_string(hide_password=False)


async def test_the_app_role_reads_nothing_without_a_tenant(app_url: str, platform: Platform) -> None:
    await platform.person()
    e = create_async_engine(app_url)
    try:
        async with e.begin() as c:
            await c.execute(sa.text(f"SET LOCAL ROLE {ROLE}"))
            assert (await c.execute(sa.select(sa.func.count()).select_from(users))).scalar_one() == 0
    finally:
        await e.dispose()


async def test_sign_in_refresh_introspect_and_invites_work_as_the_app_role(app_url: str, platform: Platform) -> None:
    p = await platform.person(roles=("admin",))
    key = await platform.api_key(p)
    store = IdentityStore(TenantDb.open(app_url))
    public = create_public_app(store, dev_signer(), demo_password=DEMO_PASSWORD, audiences=["platform"])
    internal = create_internal_app(store, services=SERVICES)
    try:
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=public), base_url="http://p") as pub,
            httpx.AsyncClient(transport=httpx.ASGITransport(app=internal), base_url="http://i") as inner,
        ):
            r = await pub.post("/v1/auth/sign-in", json={"email": p.email, "password": DEMO_PASSWORD})
            assert r.status_code == 200, r.text
            session = r.json()["data"]
            r = await pub.post("/v1/auth/refresh", json={"refreshToken": session["refreshToken"]})
            assert r.status_code == 200, r.text
            r = await inner.post("/v1/auth/introspect", json={"apiKey": key}, headers=SERVICE)
            assert r.status_code == 200, r.text
            h = {"Authorization": f"Bearer {session['token']}"}
            r = await pub.post(
                "/v1/settings/members/invite", headers=h, json={"emails": ["least@bank.test"], "role": "viewer"}
            )
            token = r.json()["data"]["invites"][0]["token"]
            assert (await pub.get(f"/v1/invites/{token}")).status_code == 200
            r = await pub.post(f"/v1/invites/{token}/accept", json={"name": "Lee Stp"})
            assert r.status_code == 200, r.text
    finally:
        await store.close()


async def test_a_temp_table_cannot_shadow_what_a_lookup_reads(engine: AsyncEngine, platform: Platform) -> None:
    """Postgres searches a session's temporary schema before the function's search_path unless pg_temp is named
    last, so a definer function reading an unqualified `users` would return a temp table's forged row."""
    p = await platform.person()
    async with engine.connect() as c:
        await c.execute(
            sa.text(
                "CREATE TEMP TABLE users (tenant_id varchar, id varchar, email varchar, name varchar, status varchar)"
            )
        )
        await c.execute(
            sa.text("INSERT INTO users VALUES ('ten_forged', 'usr_forged', :e, 'Forged', 'active')"), {"e": p.email}
        )
        await c.execute(sa.text("GRANT SELECT ON users TO ops_platform_lookup"))
        rows = (await c.execute(sa.text("SELECT tenant_id, id FROM platform_users_by_email(:e)"), {"e": p.email})).all()
        await c.rollback()
    assert [tuple(r) for r in rows] == [(p.tenant_id, p.user_id)]


async def test_sign_in_lookups_work_as_the_app_role(app_url: str, signin: SignInRig) -> None:
    """The four sign-in lookups that come before a tenant is known (an email domain, a flow by state, a flow by its
    handoff, a reset token) run as the deployment's role: options, an OIDC round trip and a password reset."""
    await signin.oidc(f"least.{signin.zone}")
    assert (await signin.configure("sip_pw", {"kind": "password", "label": "Password"})).status_code == 200
    await signin.person(f"pw@least-pw.{signin.zone}")
    store = IdentityStore(TenantDb.open(app_url))
    public = create_public_app(
        store,
        dev_signer(),
        demo_password=DEMO_PASSWORD,
        audiences=["platform"],
        security_team=signin.security_team,
        signin=SignInOptions(
            password_iterations=1_000,
            password_min_length=12,
            flow_ttl_s=600,
            reset_ttl_s=3600,
            public_url=PUBLIC_URL,
            console_url=CONSOLE,
            secrets={OIDC_SECRET: SecretStr("s3cret")},
            mail=signin.mail,
            transport=signin.idp._transport,  # pyright: ignore[reportPrivateUsage]
        ),
    )
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public), base_url=PUBLIC_URL) as pub:
            rig = SignInRig(
                pub, signin.idp, signin.mail, signin.engine, signin.tenant, signin.security_team, signin.ops_team,
                signin.admin, public,
            )  # fmt: skip
            r = await pub.post("/v1/auth/options", json={"email": f"x@least.{signin.zone}"})
            assert r.json()["data"]["sso"] == {"kind": "oidc", "label": "Bank SSO"}, r.text
            done = await rig.sign_in_sso(f"teller@least.{signin.zone}")
            assert done.completed is not None and done.completed.status_code == 200, done.location
            assert (
                await pub.post("/v1/auth/password/forgot", json={"email": f"pw@least-pw.{signin.zone}"})
            ).status_code == 204
            sent = next(m for m in signin.mail.sent.values() if m.to == (f"pw@least-pw.{signin.zone}",))
            token = sent.body.split("/reset-password/")[1].split()[0]
            r = await pub.post("/v1/auth/password/reset", json={"token": token, "password": "a long new password"})
            assert r.status_code == 204, r.text
    finally:
        await store.close()
