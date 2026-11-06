"""A workspace's sign-in secrets, by failure mode: a provider names a secret the workspace never saved; a value is read
back or kept in the clear; another workspace's secret of the same name opens this one's sign-in; someone outside the
Security team saves or deletes one; a secret a provider still names is deleted."""

from __future__ import annotations

import sqlalchemy as sa

from ops_platform.store.signin_secrets import SignInSecretStore
from ops_platform.store.tables import signin_secrets
from ops_platform.store.tenancy import TenantDb
from ops_service_kit.credentials import credential_store
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings

from .conftest import DEMO_PASSWORD, IDP, OIDC_SECRET, SignInRig

PATH = "/v1/settings/sign-in/secrets"


def _oidc(domain: str, ref: str) -> dict[str, object]:
    return {
        "kind": "oidc",
        "label": "Bank SSO",
        "domains": [domain],
        "oidc": {"issuer": f"{IDP}/oidc/bank", "clientId": "ops-console", "clientSecretRef": ref},
    }


async def test_a_provider_names_only_a_secret_the_workspace_saved_and_its_value_never_comes_back(
    signin: SignInRig,
) -> None:
    name = f"OKTA_{new_id('s')[-6:].upper()}"
    missing = await signin.configure("sip_okta", _oidc(f"okta.{signin.zone}", name))
    assert (missing.status_code, missing.json()["error"]["code"]) == (400, "secret_missing"), missing.text
    saved = await signin.public.put(f"{PATH}/{name}", json={"value": "okta-client-secret"}, headers=signin.admin)
    assert saved.status_code == 200 and saved.json()["data"]["version"] == 1, saved.text
    again = await signin.public.put(f"{PATH}/{name}", json={"value": "okta-rotated"}, headers=signin.admin)
    assert again.json()["data"]["version"] == 2 and again.json()["data"]["rotatedAt"], again.text
    assert (await signin.configure("sip_okta", _oidc(f"okta.{signin.zone}", name))).status_code == 200
    names = await signin.public.get("/v1/settings/sign-in/secret-names", headers=signin.admin)
    assert name in names.json()["data"]
    listed = await signin.public.get(PATH, headers=signin.admin)
    assert "okta-rotated" not in listed.text and "okta-client-secret" not in listed.text
    async with signin.engine.connect() as c:
        stored = (await c.execute(sa.select(signin_secrets.c.ciphertext).where(signin_secrets.c.name == name))).all()
    assert len(stored) == 1 and "okta-rotated" not in str(stored[0][0])


async def test_another_workspaces_secret_of_the_same_name_opens_nothing_here(signin: SignInRig) -> None:
    store = SignInSecretStore(TenantDb(signin.engine), credential_store(Settings()))
    assert await store.value(signin.tenant, OIDC_SECRET) == "s3cret"
    assert await store.value(f"{signin.tenant}_other", OIDC_SECRET) is None


async def test_only_a_security_team_admin_saves_or_deletes_a_secret_and_one_in_use_stays(signin: SignInRig) -> None:
    email = f"team.admin.{new_id('u')[-6:]}@{signin.zone}"
    await signin.person(email, role="admin")
    async with signin.engine.connect() as c:
        team = (await c.execute(sa.text("select team_id from members where email = :e"), {"e": email})).scalar_one()
    r = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    other = {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}
    assert (await signin.public.put(f"{PATH}/X", json={"value": "v"}, headers=other)).status_code == 403
    assert (await signin.public.delete(f"{PATH}/{OIDC_SECRET}", headers=other)).status_code == 403
    await signin.oidc(f"inuse.{signin.zone}")
    held = await signin.public.delete(f"{PATH}/{OIDC_SECRET}", headers=signin.admin)
    assert (held.status_code, held.json()["error"]["code"]) == (409, "secret_in_use"), held.text
    spare = f"SPARE_{new_id('s')[-6:].upper()}"
    assert (await signin.public.put(f"{PATH}/{spare}", json={"value": "v"}, headers=signin.admin)).status_code == 200
    assert (await signin.public.delete(f"{PATH}/{spare}", headers=signin.admin)).status_code == 204
    assert spare not in (await signin.public.get(PATH, headers=signin.admin)).text
